# Local reinforcement learning and teacher answers

NISHA uses a contextual bandit with Beta-Bernoulli Thompson sampling to choose
reply presentation. It also trains a small neural reward model from explicit answer
ratings. The neural network hashes question words into 128 inputs, uses 16 hidden
units and one helpfulness output, and learns which presentation tends to
receive helpful ratings for similar questions. It does not update the language
model's weights, speech recognizer, wake detector or action permissions.
There are no additional model downloads or training dependencies.

## Use it

After an eligible informational or conversational answer, say **"good answer"**, **"that was helpful"**,
**"bad answer"**, or **"that was not helpful"**. Typed `/feedback good` and
`/feedback bad` also work. Feedback rates the most recent eligible generated answer
in the current session. After another action or conversation turn, an earlier
answer cannot accidentally receive that rating. You can also rate the last answer
through **Ctrl+L → Response learning and teacher answers**.

The policy learns separately for technical questions, other explanations, greetings,
directly stated difficult/positive feelings, and everyday chat. Informational answers
choose direct presentation, a compact example, or a few steps. Casual replies choose
brief warmth, reflecting what you said, or a gentle follow-up. Tool execution,
generated documents and explicit formatting requests do not explore.
Current instructions, durable format preferences, brevity, language and permission
checks take precedence. General answer ratings are an imperfect signal for
presentation quality; factual corrections still belong in conversation learning.

Reward is 1 for helpful and 0 for unhelpful. Each answer has at most one rating;
changing a rating replaces it. Unrated, interrupted and failed generations earn
no reward. Successful text generation does not prove an action succeeded.
After at least 30 ratings across at least 12 distinct questions, including at least
8 helpful and 8 unhelpful ratings, NISHA fits the local reward model. It keeps
different questions out of training and validation sets and activates the model
only if it predicts held-out ratings better than a simple per-presentation baseline.
Its prediction adds a small preference to the bandit; explicit format requests and
saved preferences still take priority. Ratings are the training data, so this
optimizes presentation feedback rather than verifying factual correctness.
The direct-answer arm starts with a Beta(3,1) prior; other arms use Beta(1,1).
Exploration applies only to presentation. No real-world action is selected by RL.

Say **"show response learning"**, **"pause response learning"**,
**"resume response learning"**, or **"reset response learning"** for controls.
Resetting response preferences also resets this learned presentation policy.
Pausing persists across restarts. Reset clears reward counts without changing the pause setting
or deleting reviewed teacher examples. Remove an example separately to remove its influence.
Reset also deletes the trained reward-model weights. The learned weights contain
no raw question text; raw ratings and answers still follow the existing retention rule.

## Natural conversation on each turn

Every eligible casual reply uses the local policy and can receive feedback. Say
**"that sounded natural"**, **"I like how you said that"**, **"you sound robotic"**,
or **"that sounded unnatural"** to rate the most recent conversational reply.
Quoted or negated feedback is not counted. A reply is not rewarded simply because
you continued talking, stayed silent or did not correct it.

**"Too many questions"** or **"stop asking so many questions"** also saves a lasting
preference against conversational follow-ups. **"You can ask me questions"** permits
gentle questions again. The policy avoids selecting another follow-up immediately
after NISHA asked a question. Quiet controls keep their existing behavior.

In the teacher-review dialog, select an answer and choose **Conversation example:
warm and direct**, **reflect what I said**, or **gentle follow-up** before accepting.
Use one casual user message and its model reply, for example `Hello` and a natural
greeting. Existing approved external-task results can be reviewed this way, or you
can paste examples. No new external call happens on each chat turn.

Reviewed conversation examples provide a small capped starting preference for the
selected approach in that context. Repeated reuse never manufactures additional
positive ratings. Up to two matching demonstrations guide cadence in later local
replies, within the token budget after preserving recent real conversation. They
are explicitly marked as examples, not real user history, facts or instructions;
they are excluded from ordinary factual knowledge search. A sad-message example
does not get selected for a happy-message context. Context matching uses simple
English phrase rules, not a trained emotion classifier, so paraphrases can be missed.
Removing an example removes its starting preference and future retrieval; past
explicit ratings of NISHA's replies remain until you reset response learning.

## Learn from other models

Open the same dialog and paste the source model name, exact question and answer.
This requires no network access. Results from the existing external-task dialog
can be queued automatically when **Save the answer for local learning review** is
checked. The existing external-tasks switch and exact-task approval still apply;
this feature never automatically calls a provider or transmits conversation history.

Select an answer, read the preview, and click **Accept selected reviewed answer**.
With the reference-knowledge choice, it becomes locally searchable knowledge, with its source model
and unverified status preserved. Review expresses your choice to use the answer;
it does not establish that all its facts are correct. Teacher answers cannot become
personal facts, overwrite response preferences, execute commands, or grant approval.

For a preferred-answer comparison, check **I prefer this answer to NISHA's last
answer to the same question** before adding the pasted answer. The exact question
must match the recorded local answer. Accepting this reviewed comparison makes it
eligible for **Export reviewed preference pairs locally (JSONL)**. The export contains
`prompt`, `chosen`, `rejected` and `provider` fields. It is a dataset for a later,
separately evaluated DPO/adapter-training workflow; exporting does not train weights.
Teacher comparisons do not award presentation rewards automatically.

## Storage, removal and limits

Policy decisions, feedback and teacher examples stay in `data/nisha.sqlite3`.
Raw decision text and pending teacher answers expire according to the existing
history retention setting when the core starts. Expired rated decisions become
aggregate win/loss counts with no prompt, answer or session identifier. This keeps
presentation learning while allowing raw conversation data to expire.
Reviewed teacher answers are explicitly retained knowledge until removed.
Forget the teacher answer in the review dialog, or forget its knowledge source in
Ctrl+L. Either removes it from retrieval and future preference-pair exports.
Previously exported files remain at their displayed paths under `data/learning_exports`;
delete an export separately if it is no longer wanted. Normal transcript/task retention
still applies to copies already recorded in those histories.

Testing covers policy improvement in a seeded simulation, feedback attribution,
restart persistence, rating replacement, explicit-instruction priority, cancelled
generation, retention, reset, teacher quarantine/review/deletion, safe context roles,
approval boundaries and exact-prompt dataset exports. Synthetic tests establish
the learning mechanism; real answer quality still needs your ratings and evaluation.
RL does not repair microphone recognition, missing app integrations or factual
errors by itself. No automatic online model-weight training is installed.

In a deterministic simulation (seed 17), the example arm was selected 96 times out
of 500 before feedback, and 455 times out of 500 after 40 positive example ratings.
This verifies that feedback changes policy selection; it is not a measurement of
real-world answer accuracy. The desktop smoke check uses a mock provider and
temporary storage, verifies review before retrieval, and makes no external request.
