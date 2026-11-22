"""Local contextual bandit for reply presentation; never selects tools or permissions."""

import json
import random
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nisha import answer_quality
from nisha.conversation_style import CONVERSATION_ARMS, conversation_context, policy_context
from nisha.knowledge import Knowledge
from nisha.storage import now

ARMS = {
    "direct": "Present the answer directly, starting with the main point.",
    "example": "Where helpful, use one compact concrete example to explain the answer.",
    "steps": "Where helpful, organize the answer into a few clear steps or points.",
}
ALL_ARMS = ARMS | CONVERSATION_ARMS
POSITIVE = {"good answer", "that was helpful", "that answer was helpful", "/feedback good"}
NEGATIVE = {"bad answer", "that was not helpful", "that answer was unhelpful", "/feedback bad"}
CONVERSATION_POSITIVE = {"that sounded natural", "i like how you said that", "that felt natural"}
CONVERSATION_NEGATIVE = {
    "that sounded robotic",
    "you sound robotic",
    "that sounded unnatural",
    "too many questions",
    "stop asking so many questions",
}


class Reinforcement:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS response_decisions (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id INTEGER NOT NULL,
                    context TEXT NOT NULL, arm TEXT NOT NULL, prompt TEXT NOT NULL,
                    answer TEXT NOT NULL, reward INTEGER CHECK(reward IN (0,1)),
                    created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS decision_session ON response_decisions(session_id,turn_id);
                CREATE TABLE IF NOT EXISTS teacher_examples (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, prompt TEXT NOT NULL,
                    answer TEXT NOT NULL, decision_id TEXT, source_id TEXT,
                    reviewed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reinforcement_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS response_reward_totals (
                    context TEXT NOT NULL, arm TEXT NOT NULL, wins INTEGER NOT NULL,
                    losses INTEGER NOT NULL, PRIMARY KEY(context,arm));
                CREATE TABLE IF NOT EXISTS conversation_teachers (
                    teacher_id TEXT PRIMARY KEY, context TEXT NOT NULL, style TEXT NOT NULL);
            """)

    def enabled(self):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT value FROM reinforcement_settings WHERE key='enabled'"
            ).fetchone()
        return row is None or row[0] == "1"

    def set_enabled(self, enabled):
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO reinforcement_settings VALUES('enabled',?)",
                (str(int(enabled)),),
            )

    def choose(self, text, preferences, rng=None, previous_reply=""):
        # Direct instructions and persistent formatting preferences override exploration.
        if (
            not self.enabled()
            or "format" in preferences
            or re.search(
                r"\b(?:steps?|bullets?|paragraphs?|examples?|only|just answer)\b",
                text,
                re.IGNORECASE,
            )
        ):
            return None
        context = policy_context(text)
        if context is None:
            return None
        scores = self.scores(context)
        model = self.quality_model()
        if model:
            for arm in scores:
                estimate = answer_quality.predict(model["weights"], text, context, arm)
                scores[arm][0] += 2 * estimate
                scores[arm][1] += 2 * (1 - estimate)
        if conversation_context(context) and (
            "?" in previous_reply or preferences.get("follow_up", {}).get("value") == "none"
        ):
            scores.pop("curious", None)
        rng = rng or random
        arm = max(scores, key=lambda key: rng.betavariate(*scores[key]))
        return context, arm

    def scores(self, context):
        # Beta-Bernoulli Thompson sampling, with a mild direct-answer prior.
        arms = CONVERSATION_ARMS if conversation_context(context) else ARMS
        scores = {arm: [3 if arm in {"direct", "warm"} else 1, 1] for arm in arms}
        with self.store.connect() as db:
            # Reviewed demonstrations provide a capped prior, never automatic repeated rewards.
            for row in db.execute(
                "SELECT c.style,COUNT(*) n FROM conversation_teachers c "
                "JOIN teacher_examples t ON t.id=c.teacher_id "
                "JOIN knowledge_sources k ON k.id=t.source_id "
                "WHERE t.reviewed=1 AND c.context=? GROUP BY c.style",
                (context,),
            ):
                if row["style"] in scores:
                    scores[row["style"]][0] += min(row["n"], 2)
            for row in db.execute(
                "SELECT * FROM response_reward_totals WHERE context=?", (context,)
            ):
                if row["arm"] in scores:
                    scores[row["arm"]][0] += row["wins"]
                    scores[row["arm"]][1] += row["losses"]
            for row in db.execute(
                "SELECT arm,reward,COUNT(*) n FROM response_decisions WHERE context=? "
                "AND reward IS NOT NULL GROUP BY arm,reward",
                (context,),
            ):
                if row["arm"] in scores:
                    scores[row["arm"]][0 if row["reward"] else 1] += row["n"]
        return scores

    def record(self, session, turn_id, choice, prompt, answer):
        if choice is None:
            return
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO response_decisions VALUES(?,?,?,?,?,?,?,NULL,?)",
                (uuid4().hex, session, turn_id, *choice, prompt, answer, now()),
            )

    def latest(self, session):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT d.* FROM response_decisions d WHERE session_id=? "
                "AND turn_id=(SELECT MAX(id) FROM turns WHERE session_id=? AND role='assistant')",
                (session, session),
            ).fetchone()
            outcome = db.execute(
                "SELECT status,created_at FROM turn_outcomes WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (session,),
            ).fetchone()
            if (
                row
                and outcome
                and outcome["status"] in {"failed", "interrupted"}
                and outcome["created_at"] >= row["created_at"]
            ):
                return None
        return dict(row) if row else None

    def compared_answer(self, identifier):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT answer FROM response_decisions WHERE id=?", (identifier,)
            ).fetchone()
        return row[0] if row else "Original answer no longer retained."

    def feedback(self, session, reward):
        if type(reward) is not int or reward not in (0, 1):
            raise ValueError("Feedback must be good or bad.")
        if not self.enabled():
            return "Response learning is paused."
        row = self.latest(session)
        if not row:
            return "No eligible generated answer to rate in this conversation."
        with self.store.connect() as db:
            # One replaceable rating per answer; repeated feedback cannot inflate rewards.
            db.execute("UPDATE response_decisions SET reward=? WHERE id=?", (reward, row["id"]))
        self.train_quality_model()
        return "Feedback saved locally. I'll use it when choosing how to present similar answers."

    def quality_model(self):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT value FROM reinforcement_settings WHERE key='answer_quality_model'"
            ).fetchone()
        if not row:
            return None
        try:
            model = json.loads(row[0])
            if (
                model.get("architecture") != "hashed_words_128_tanh_16_sigmoid_1"
                or model.get("samples", 0) < 30
                or not isinstance(model.get("weights"), dict)
            ):
                return None
            return model
        except (ValueError, TypeError):
            return None

    def train_quality_model(self):
        with self.store.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT context,arm,prompt,reward FROM response_decisions "
                "WHERE reward IS NOT NULL ORDER BY created_at,id"
            )]
        model = answer_quality.train(rows)
        with self.store.connect() as db:
            if model:
                db.execute(
                    "INSERT OR REPLACE INTO reinforcement_settings VALUES('answer_quality_model',?)",
                    (json.dumps(model),),
                )
            else:
                db.execute("DELETE FROM reinforcement_settings WHERE key='answer_quality_model'")
        return model

    def handle(self, text, session):
        value = text.casefold().strip(" .!?")
        if value in POSITIVE | NEGATIVE:
            return self.feedback(session, int(value in POSITIVE))
        if value in CONVERSATION_POSITIVE | CONVERSATION_NEGATIVE:
            if value in {"too many questions", "stop asking so many questions"}:
                from nisha.preferences import Preferences

                Preferences(self.store).set("follow_up", "none", text)
            row = self.latest(session)
            if row and conversation_context(row["context"]):
                return self.feedback(session, int(value in CONVERSATION_POSITIVE))
            return "I'll keep the conversation natural. There isn't a recent conversational reply to rate."
        if value in {"show response learning", "/reinforcement"}:
            return self.status()
        if value in {"pause response learning", "resume response learning"}:
            self.set_enabled(value.startswith("resume"))
            return "Response learning resumed." if self.enabled() else "Response learning paused."
        if value == "reset response learning":
            self.reset()
            return "Response ratings and learned presentation choices cleared locally."
        return None

    def reset(self):
        with self.store.connect() as db:
            db.execute("DELETE FROM response_decisions")
            db.execute("DELETE FROM response_reward_totals")
            db.execute("DELETE FROM reinforcement_settings WHERE key='answer_quality_model'")
            db.execute("UPDATE teacher_examples SET decision_id=NULL")

    def status(self):
        with self.store.connect() as db:
            rated = db.execute(
                "SELECT COUNT(*) FROM response_decisions WHERE reward IS NOT NULL"
            ).fetchone()[0]
            rated += db.execute(
                "SELECT COALESCE(SUM(wins+losses),0) FROM response_reward_totals"
            ).fetchone()[0]
            pending = db.execute(
                "SELECT COUNT(*) FROM teacher_examples WHERE reviewed=0"
            ).fetchone()[0]
        model = self.quality_model()
        quality = (
            f"Trained answer presentation model active from {model['samples']} ratings."
            if model else "Answer presentation model waiting for enough validated ratings."
        )
        return f"Local response learning: {'enabled' if self.enabled() else 'paused'}. {rated} rated answers; {pending} teacher answers awaiting review. {quality} Language model weights are unchanged."

    def prune(self, days):
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO response_reward_totals SELECT context,arm,SUM(reward),SUM(1-reward) "
                "FROM response_decisions WHERE created_at < ? AND reward IS NOT NULL GROUP BY context,arm "
                "ON CONFLICT(context,arm) DO UPDATE SET wins=wins+excluded.wins,losses=losses+excluded.losses",
                (cutoff,),
            )
            # Honor transcript retention for raw requests and answers, including rated ones.
            db.execute("DELETE FROM response_decisions WHERE created_at < ?", (cutoff,))
            db.execute(
                "DELETE FROM teacher_examples WHERE reviewed=0 AND created_at < ?", (cutoff,)
            )
            db.execute(
                "DELETE FROM conversation_teachers WHERE teacher_id NOT IN (SELECT id FROM teacher_examples)"
            )

    def propose_teacher(self, provider, prompt, answer, decision_id=None):
        provider, prompt, answer = provider.strip(), prompt.strip(), answer.strip()
        if (
            not provider
            or len(provider) > 200
            or not prompt
            or len(prompt) > 50_000
            or not answer
            or len(answer) > 100_000
        ):
            raise ValueError(
                "Provide a model name, a prompt up to 50,000 characters and an answer up to 100,000 characters."
            )
        with self.store.connect() as db:
            if decision_id:
                decision = db.execute(
                    "SELECT * FROM response_decisions WHERE id=?", (decision_id,)
                ).fetchone()
                if not decision or decision["prompt"] != prompt or decision["answer"] == answer:
                    raise ValueError(
                        "A comparison must use the exact original prompt and a different answer."
                    )
            duplicate = db.execute(
                "SELECT id FROM teacher_examples WHERE provider=? AND prompt=? AND answer=? AND decision_id IS ?",
                (provider, prompt, answer, decision_id),
            ).fetchone()
            if duplicate:
                return duplicate[0]
            identifier = uuid4().hex
            db.execute(
                "INSERT INTO teacher_examples VALUES(?,?,?,?,?,NULL,0,?)",
                (identifier, provider, prompt, answer, decision_id, now()),
            )
        return identifier

    def teachers(self):
        with self.store.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT t.*,c.style conversation_style FROM teacher_examples t LEFT JOIN conversation_teachers c ON c.teacher_id=t.id ORDER BY t.created_at DESC"
                )
            ]

    def accept_teacher(self, identifier, conversation_style=None):
        if conversation_style is not None and conversation_style not in CONVERSATION_ARMS:
            raise ValueError("Choose a supported conversational approach.")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM teacher_examples WHERE id=?", (identifier,)).fetchone()
            existing_style = db.execute(
                "SELECT style FROM conversation_teachers WHERE teacher_id=?", (identifier,)
            ).fetchone()
        if not row:
            raise ValueError("Teacher answer not found.")
        if row["reviewed"]:
            if (existing_style[0] if existing_style else None) != conversation_style:
                raise ValueError(
                    "This answer was already reviewed. Forget it and add it again to change its use."
                )
            return row["source_id"]
        context = policy_context(row["prompt"])
        if conversation_style and not conversation_context(context):
            raise ValueError(
                "For a conversation example, use one casual user message and the model's reply, rather than a task or factual question."
            )
        source = Knowledge(self.store).add_text(
            "Reviewed teacher: " + row["provider"],
            "Teacher reference: "
            + identifier
            + "\nSource model: "
            + row["provider"]
            + "\nQuestion: "
            + row["prompt"]
            + "\nAnswer: "
            + row["answer"],
            "conversation_style_example"
            if conversation_style
            else "reviewed_external_model_output_unverified",
        )
        with self.store.connect() as db:
            db.execute(
                "UPDATE teacher_examples SET source_id=?,reviewed=1 WHERE id=?",
                (source, identifier),
            )
            if conversation_style:
                db.execute(
                    "INSERT INTO conversation_teachers VALUES(?,?,?)",
                    (identifier, context, conversation_style),
                )
        return source

    def forget_teacher(self, identifier):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT source_id FROM teacher_examples WHERE id=?", (identifier,)
            ).fetchone()
            if row and row[0]:
                db.execute("DELETE FROM knowledge_search WHERE source_id=?", (row[0],))
                db.execute("DELETE FROM knowledge_sources WHERE id=?", (row[0],))
            db.execute("DELETE FROM teacher_examples WHERE id=?", (identifier,))
            db.execute("DELETE FROM conversation_teachers WHERE teacher_id=?", (identifier,))

    def conversation_examples(self, text, choice):
        if not choice or not conversation_context(choice[0]) or not self.enabled():
            return []
        with self.store.connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT t.id,t.provider,t.prompt,t.answer,c.style FROM teacher_examples t "
                    "JOIN conversation_teachers c ON c.teacher_id=t.id "
                    "JOIN knowledge_sources k ON k.id=t.source_id "
                    "WHERE t.reviewed=1 AND c.context=? AND c.style=? ORDER BY t.created_at DESC LIMIT 100",
                    choice,
                )
            ]
        words = set(re.findall(r"\w+", text.casefold()))
        rows.sort(
            key=lambda row: len(words & set(re.findall(r"\w+", row["prompt"].casefold()))),
            reverse=True,
        )
        return [
            {
                "source_model": row["provider"],
                "example_user": row["prompt"][:400],
                "example_reply": row["answer"][:700],
            }
            for row in rows[:2]
        ]

    def preference_pairs(self):
        # Only explicit reviewed comparisons, never synthetic self-ratings or raw histories.
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT t.prompt,t.answer chosen,d.answer rejected,t.provider FROM teacher_examples t "
                "JOIN response_decisions d ON d.id=t.decision_id "
                "JOIN knowledge_sources k ON k.id=t.source_id WHERE t.reviewed=1"
            )
            return [dict(row) for row in rows]

    def export_pairs(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("preferences-" + uuid4().hex + ".jsonl")
        with path.open("x", encoding="utf-8") as output:
            for pair in self.preference_pairs():
                output.write(json.dumps(pair, ensure_ascii=False) + "\n")
        return path
