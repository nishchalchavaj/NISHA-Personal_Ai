import re
from collections.abc import Iterator
from contextlib import nullcontext
from threading import RLock, local
from time import monotonic
from urllib.parse import urlparse

from nisha.actions import WebsiteActions
from nisha.automation import Automation
from nisha.connections import Connections, Step
from nisha.context import ContextBuilder
from nisha.conversation_learning import ConversationLearning, eligible
from nisha.devices import Devices
from nisha.errors import (
    ConfigurationError,
    ModelUnavailable,
    NishaError,
    OperationCancelled,
    PrivacyError,
)
from nisha.gateway import Gateway
from nisha.knowledge import Knowledge
from nisha.live_weather import LiveWeather, weather_request
from nisha.local_utilities import LocalUtilities
from nisha.memory import MemoryBackend
from nisha.music import SpotifyControl, spotify_request
from nisha.pc_control import PCControl
from nisha.preferences import Preferences
from nisha.reinforcement import ALL_ARMS, Reinforcement
from nisha.storage import Store
from nisha.system_actions import SystemActions
from nisha.window_actions import WindowActions
from nisha.workers import ExternalWorkers
from nisha.workflows import WorkflowService


class NishaCore:
    def __init__(
        self,
        settings,
        gateway=None,
        store=None,
        memory: MemoryBackend | None = None,
        actions=None,
        workflows=None,
    ):
        self.settings = settings
        self.gateway = gateway or Gateway(settings)
        self.store = store or Store(settings.data_dir / "nisha.sqlite3")
        self.memory = memory or self.store
        self.preferences = Preferences(self.store)
        self.reinforcement = Reinforcement(self.store)
        self.reinforcement.prune(settings.history_retention_days)
        self.learning = ConversationLearning(settings, self.store)
        self._touched_sessions = set()
        self._latest_assistant_context = {}
        self.current_surface = {}
        self.browser_searches = {}
        from nisha.interaction import Interaction

        self.interaction = Interaction(self.store)
        self.knowledge = Knowledge(self.store)
        self.workers = ExternalWorkers(settings.data_dir, enabled=settings.external_tasks_enabled)
        self.actions = actions or WebsiteActions()
        self.workflows = workflows or WorkflowService(settings)
        self.window_actions = WindowActions()
        self.pc_control = PCControl()
        from nisha.screen import ScreenService

        self.screen = ScreenService(settings.ollama_url, settings.vision_model)
        self.music = SpotifyControl(self.workflows.desktop, self.pc_control)
        self.weather = LiveWeather()
        self.local_utilities = LocalUtilities(settings.data_dir / "workspace")
        self.system_actions = SystemActions(self.workflows.desktop)
        self.connections = Connections(settings.data_dir)
        from nisha.coding import ProjectCodingAgent
        from nisha.versioning import CandidateManager

        self.coding = ProjectCodingAgent(self.connections, settings.data_dir, self.store)
        self.candidates = CandidateManager(self.coding, settings.data_dir, self.store)
        from nisha.terminal import TerminalService

        self.terminal = TerminalService(self.connections, settings.data_dir, self.store)
        self.startup_recovery = self.candidates.recover_interrupted()
        from nisha.diagnostics import Diagnostics
        from nisha.improvement import ImprovementRunner
        from nisha.research import WebResearchAgent

        self.diagnostics = Diagnostics(self.coding, self.store, settings.data_dir)
        self.improvement = ImprovementRunner(self.coding, self.candidates, self.store)
        self.research_agent = WebResearchAgent(self.connections, store=self.store)
        self.devices = Devices(self.connections)
        self.automation = Automation(
            self.connections, self.devices, self.workflows.desktop, settings.data_dir
        )
        self.speech_pending = {}
        self.store.prune_transcripts(settings.history_retention_days)
        self.context = ContextBuilder(settings, self.store, self.gateway)
        self._lock = RLock()  # one assistant turn at a time; SQLite is opened per operation
        self._action_lock = RLock()
        self._thread_state = local()
        self._cancelled = None

    @property
    def _cancelled(self):
        return getattr(self._thread_state, "cancelled", None)

    @_cancelled.setter
    def _cancelled(self, value):
        self._thread_state.cancelled = value

    def close(self):
        for session in self._touched_sessions:
            self.learning.queue(session)
        if isinstance(self.gateway, Gateway):
            self.learning.launch()
        self.gateway.close()

    def end_conversation(self, session):
        return self.learning.queue(session)

    def new_session(self):
        self.speech_pending.clear()
        youtube = getattr(getattr(self, "actions", None), "youtube", None)
        if youtube:
            youtube.pending.clear()
        self.system_actions.pending.clear()
        return self.store.new_session()

    def route(self, session, alias):
        if alias == "auto":
            alias = "local_fast"
        if alias not in self.settings.models:
            raise ConfigurationError("That model alias is not configured. Check config/nisha.yaml.")
        profile = self.settings.models[alias]
        self.store.history(session)
        if not profile.local:
            raise PrivacyError(
                "NISHA's base conversation is local-only. External models are standalone task workers."
            )
        return alias

    def check_cancelled(self):
        if self._cancelled and self._cancelled():
            raise OperationCancelled("Operation cancelled.")

    def stream(
        self, text, session, alias="auto", uncertain=False, assistant_prompt=None, cancelled=None
    ):
        with self._lock:
            previous = self._cancelled
            self._cancelled = cancelled
            try:
                with (
                    self.gateway.cancellation(cancelled)
                    if hasattr(self.gateway, "cancellation")
                    else nullcontext()
                ):
                    yield from self._recorded_stream(
                        text, session, alias, uncertain, assistant_prompt
                    )
            finally:
                self._cancelled = previous

    def _recorded_stream(self, text, session, alias, uncertain, assistant_prompt):
        import logging

        started = monotonic()
        first = True
        try:
            for chunk in self._stream(text, session, alias, uncertain, assistant_prompt):
                if first:
                    logging.getLogger("nisha").info(
                        "Reply first text in %.2fs; model=%s.", monotonic() - started, alias
                    )
                    first = False
                yield chunk
            self.store.record_outcome(
                session, text, "clarification_requested" if uncertain else "response_complete"
            )
        except OperationCancelled:
            self.store.record_outcome(session, text, "interrupted")
            raise
        except (NishaError, ValueError) as exc:
            self.store.record_outcome(session, text, "failed", type(exc).__name__)
            raise
        except GeneratorExit:
            self.store.record_outcome(session, text, "interrupted")
            raise

    def _stream(
        self, text, session, alias="auto", uncertain=False, assistant_prompt=None
    ) -> Iterator[str]:
        text = text.strip()
        if not text or len(text) > 50_000:
            raise ValueError("Enter a message of 1–50000 characters.")
        with self._lock:
            self.check_cancelled()
            alias = self.route(session, alias)
            from nisha.listening import WakeGate

            wake = WakeGate(
                self.settings.voice.wake_word, aliases=self.settings.voice.wake_aliases
            ).pattern.search(text)
            if wake:
                text = text[wake.end() :].strip(" ,.!?:;")
                if not text:
                    reply = "Yes, Boss?"
                    self.store.exchange(session, "NISHA", reply, cloud_allowed=False)
                    yield reply
                    return
            if uncertain:
                self.speech_pending[session] = {"text": text, "expires": monotonic() + 120}
                reply = f"I heard '{text}', but the audio wasn't clear. Say 'confirm command' to use that exact wording, or repeat your request."
                self.store.exchange(session, text, reply, cloud_allowed=False)
                yield reply
                return
            if session in self.speech_pending:
                pending = self.speech_pending.pop(session)
                pending_action = re.fullmatch(
                    r"(?:please )?(?:open|launch|start) (?:the )?([a-z][a-z0-9 ]+)",
                    pending["text"].casefold().strip(" .!?"),
                )
                repeat_target = bool(
                    pending_action and text.casefold().strip(" .!?") == pending_action[1]
                )
                if text.casefold().strip(".! ") == "confirm command" or repeat_target:
                    if pending["expires"] < monotonic():
                        reply = (
                            "That unclear command confirmation expired. Please repeat your request."
                        )
                        self.store.exchange(session, text, reply, cloud_allowed=False)
                        yield reply
                        return
                    text = pending["text"]
            _, history = self.store.history(session)
            feedback_reply = self.reinforcement.handle(text, session)
            if feedback_reply is not None:
                self.store.exchange(session, text, feedback_reply, cloud_allowed=False)
                yield feedback_reply
                return
            self.learning.observe(
                session,
                text,
                self._latest_assistant_context.get(
                    session, history[-1]["content"] if history else ""
                ),
            )
            self._touched_sessions.add(session)
            self.preferences.observe(text)
            if eligible(text):
                self.interaction.observe(text)
            action_reply = self.learning_command(text)
            if action_reply is None:
                action_reply = self.interaction.handle(text)
            if action_reply is None:
                action_reply = self.preferences.handle(text)
            if action_reply is None:
                action_reply = self.knowledge.handle(text)
            if action_reply is None and self.settings.instant_smalltalk:
                from nisha.responsiveness import quick_reply

                previous_reply = history[-1]["content"] if history else ""
                fast_choice = self.reinforcement.choose(
                    text, self.preferences.all(), previous_reply=previous_reply
                )
                fast = quick_reply(text, fast_choice[1] if fast_choice else "warm", previous_reply)
                if fast:
                    turn_id = self.store.exchange(session, text, fast, cloud_allowed=False)
                    self.reinforcement.record(session, turn_id, fast_choice, text, fast)
                    self._latest_assistant_context[session] = fast
                    yield fast
                    return
            if action_reply is None:
                from nisha.dialogue import is_action_intent, resolve_followup, unsupported_action
                from nisha.responsiveness import action_request

                # A running background action must not hold up ordinary conversation.
                action_text = resolve_followup(text, history)
                acquired = self._action_lock.acquire(
                    blocking=action_request(action_text) or self.automation.matches_trigger(action_text)
                )
                if acquired:
                    try:
                        action_reply = self.handle_action(action_text, session, history, alias)
                    finally:
                        self._action_lock.release()
                    if action_reply is None and is_action_intent(action_text):
                        action_reply = unsupported_action(action_text)
                elif re.match(
                    r"^(?:/|approve\b|send\b|cancel email\b|revise\b|rewrite\b|subscribe\b|like (?:this|that)\b)",
                    text,
                    re.IGNORECASE,
                ):
                    action_reply = "Another action is still running. Please repeat this command when it finishes."
            if action_reply is not None:
                self._latest_assistant_context[session] = action_reply[:600]
                self.store.exchange(session, text, action_reply, cloud_allowed=False)
                yield action_reply
                return
            memories = self.memory.search(text, limit=8)
            choice = self.reinforcement.choose(
                text,
                self.preferences.all(),
                previous_reply=history[-1]["content"] if history else "",
            )
            messages = self.context.build(
                session,
                text,
                alias,
                memories,
                assistant_prompt=assistant_prompt,
                presentation=ALL_ARMS[choice[1]] if choice else None,
                conversation_examples=self.reinforcement.conversation_examples(text, choice),
                defer_summary=bool(
                    self.settings.instant_smalltalk and choice and choice[0].startswith("social_")
                ),
            )
            chunks = []
            self._latest_assistant_context[session] = ""
            _, brief = self.preferences.style(text)
            response = (
                self.gateway.respond(alias, messages, brief)
                if hasattr(self.gateway, "respond")
                else self.gateway.stream(alias, messages)
            )
            for chunk in response:
                self.check_cancelled()
                chunks.append(chunk)
                self._latest_assistant_context[session] = "".join(chunks)[:600]
                yield chunk
            reply = "".join(chunks).strip()
            if not reply:
                raise ModelUnavailable("The model returned no text. Please retry.")
            turn_id = self.store.exchange(session, text, reply, cloud_allowed=False)
            self.reinforcement.record(session, turn_id, choice, text, reply)

    def chat(self, text, session, alias="auto"):
        return "".join(self.stream(text, session, alias)).strip()

    def handle_action(self, text, session, history, alias):
        self.check_cancelled()
        from nisha.dialogue import strip_trailing_address

        text = strip_trailing_address(text)
        from nisha.screen import screen_question

        if (question := screen_question(text)) is not None:
            try:
                result = self.screen.analyze(question or None)
            except (NishaError, OSError, ValueError) as exc:
                self.store.audit("screen_analysis", "failed")
                return f"I couldn't analyze the current screen: {exc}"
            self.store.audit("screen_analysis", "completed")
            return result
        research_request = re.fullmatch(
            r"(?:please )?research project (.+?) for (.{2,500})",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if research_request:
            try:
                result = self.diagnostics.research(
                    research_request[1].strip(), research_request[2].strip()
                )
            except NishaError as exc:
                return f"I couldn't research that project: {exc}"
            return "Local project evidence:\n" + (
                "\n".join(
                    f"{item['path']}:{item['line']}: {item['text']}"
                    for item in result["evidence"]
                )
                or "No matching source or documentation lines found."
            )
        web_research_request = re.fullmatch(
            r"(?:please )?(?:web research|research the web|search the web) for (.{2,500})",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if web_research_request:
            try:
                result = self.research_agent.research(
                    web_research_request[1].strip(), self, session, alias
                )
            except NishaError as exc:
                return f"I couldn't complete web research: {exc}"
            sources = "\n".join(
                f"{item['title']}: {item['url']}" for item in result["sources"]
            )
            return result["summary"] + ("\n\nSources:\n" + sources if sources else "")
        if re.fullmatch(r"(?:please )?debug last failure", text.strip().strip(".!?"), re.IGNORECASE):
            result = self.diagnostics.debug()
            observations = result["observations"]
            return "Recent recorded failures:\n" + (
                "\n".join(item["observation"] for item in observations)
                or "No failed verification commands are recorded."
            )
        if re.fullmatch(r"(?:please )?analyze recent failures", text.strip().strip(".!?"), re.IGNORECASE):
            result = self.diagnostics.analyze()
            return (
                f"Analysis found {len(result['failed_commands'])} failed verification commands "
                f"and {len(result['slow_commands_over_2_seconds'])} commands over two seconds. "
                "The report contains observed evidence and no inferred cause."
            )
        improvement_request = re.fullmatch(
            r"(?:please )?create experimental version of (.{1,80}?) to (.{1,4000}) using (.{1,1000})",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if improvement_request:
            files = [item.strip() for item in improvement_request[3].split(",") if item.strip()]
            try:
                result = self.improvement.run(
                    improvement_request[2].strip(),
                    improvement_request[1].strip(),
                    files,
                    self,
                    session,
                    alias,
                )
            except (NishaError, OSError, ValueError) as exc:
                return f"I couldn't complete the bounded improvement run: {exc}"
            return (
                f"Improvement run {result['status']}; experiment "
                f"{result['experiment_id']}. It remains isolated until explicit approval."
            )
        coding_request = re.fullmatch(
            r"(?:please )?(?:run (?:the )?(tests|test suite)|lint)(?: (?:in|for|project) (.+))?",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if coding_request:
            config = self.connections.load()
            project_name = coding_request[2] if coding_request[2] else config.default_project
            if not project_name:
                return "Choose a configured project first, then say 'run tests in <project>'."
            suite = "ruff" if text.casefold().strip().startswith("lint") or text.casefold().strip().startswith("please lint") else "pytest"
            try:
                receipt = self.coding.verify(project_name, suite)
            except (NishaError, OSError) as exc:
                return f"I couldn't verify {project_name}: {exc}"
            outcome = "timed out" if receipt["timed_out"] else (
                "passed" if receipt["exit_code"] == 0 else "failed"
            )
            detail = (receipt["stdout"] or receipt["stderr"]).strip()[:4000]
            return (
                f"{suite.capitalize()} {outcome} for {project_name} "
                f"({receipt['duration_seconds']:.1f}s; exit {receipt['exit_code']})."
                + ("\n" + detail if detail else "")
            )
        project_request = re.fullmatch(
            r"(?:please )?(?:inspect project|list project files in) (.+)",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if project_request:
            try:
                names = self.coding.list_files(project_request[1].strip(), limit=80)
            except NishaError as exc:
                return f"I couldn't inspect that project: {exc}"
            return "Configured project files:\n" + ("\n".join(names) or "No source files found.")
        search_request = re.fullmatch(
            r"(?:please )?search project (.+?) for (.{1,200})",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if search_request:
            try:
                matches = self.coding.search(
                    search_request[1].strip(), search_request[2].strip(), limit=30
                )
            except NishaError as exc:
                return f"I couldn't search that project: {exc}"
            return "Project matches:\n" + (
                "\n".join(
                    f"{item['path']}:{item['line']}: {item['text']}" for item in matches
                )
                or "No matching source lines found."
            )
        if utility_reply := self.local_utilities.handle(text):
            self.store.audit("local_utility", utility_reply[:240])
            return utility_reply
        if location := weather_request(text):
            return self.weather.current(location)
        if music_action := spotify_request(text, self.current_surface.get(session, "")):
            self.music.desktop = self.workflows.desktop
            reply = (
                self.music.open() if music_action == "open"
                else self.music.play(open_first=music_action == "open_play")
            )
            if getattr(self.music, "last_window_visible", False) or reply.startswith(
                ("Focused and verified ", "Spotify shows ", "Clicked Spotify's ")
            ):
                self.current_surface[session] = "spotify"
            return reply
        if re.fullmatch(
            r"(?:please )?(?:let's |lets )?(?:open|launch|start) (?:google )?chrome",
            text.casefold().strip(" .!?"),
        ):
            reply = self.pc_control.launch_and_focus(self.workflows.desktop, "chrome")
            if reply.startswith("Focused and verified "):
                self.current_surface[session] = "chrome"
            return reply
        if self.current_surface.get(session, "").casefold() in {"chrome", "google chrome"} and re.fullmatch(
            r"(?:it's not running on the foreground.*|you didn't)", text.casefold().strip(" .!?"),
        ):
            return self.pc_control.focus_app("chrome")
        text = re.sub(
            r"^(?:not default[, ]+)?i told (?:you )?(?=(?:open|launch|start) chrome\b)",
            "", text, flags=re.IGNORECASE,
        )
        browser_open = re.fullmatch(
            r"(?:please )?(?:just )?(?:open|launch|start) (.+?) in (?:google chrome|chrome|microsoft edge|edge)[.!?]*",
            text.casefold().strip(),
        )
        if browser_open:
            reply = self.workflows.handle(text, session, history, self, alias)
            if reply is not None:
                if self.workflows.last_opened_url:
                    host = urlparse(self.workflows.last_opened_url).hostname or ""
                    self.current_surface[session] = (
                        "YouTube" if host.endswith("youtube.com") else host or browser_open[1]
                    )
                    self.system_actions.forget_explorer(session)
                return reply
        from nisha.browser_commands import first_result_request

        result_target = first_result_request(text)
        if result_target is not None:
            search_context = self.browser_searches.get(session)
            if not search_context:
                return "I don't have a recent browser search to select a result from."
            browser, query = search_context
            try:
                result = self.actions.youtube.browser.request(
                    "open_google_first_result", browser=browser, query=query,
                    target=result_target,
                )
            except NishaError as exc:
                return f"I couldn't verify opening a search result in {browser}: {exc}"
            host = (urlparse(result["url"]).hostname or "").removeprefix("www.")
            self.current_surface[session] = "YouTube" if host.endswith("youtube.com") else host
            self.browser_searches.pop(session, None)
            return f"Opened {result['title']} in {browser}."
        catalog = getattr(self.workflows.desktop, "catalog", None)
        reply = catalog.handle(text) if catalog is not None else None
        if reply is not None:
            return reply
        self.system_actions.desktop = self.workflows.desktop
        reply = self.system_actions.handle(text, session)
        if reply is not None:
            opened_file = self.system_actions.opened_file.pop(session, None)
            if opened_file is not None:
                self.current_surface[session] = opened_file.name
            location = self.system_actions.explorer_location.get(session)
            if location is not None:
                self.current_surface[session] = (
                    "this pc"
                    if location == "this pc"
                    else "recycle bin"
                    if location == "recycle bin"
                    else location.name or "local disk"
                )
            return reply
        from nisha.desktop_items import handle_desktop_item

        reply = handle_desktop_item(text, history, self.workflows.desktop)
        if reply is not None:
            if reply.startswith("Asked Windows to open") or "Asked Windows to open it" in reply:
                self.system_actions.forget_explorer(session)
                named = re.search(r"(?:file|folder) (.+?) from your Desktop", reply)
                if named:
                    self.current_surface[session] = named[1]
            return reply
        search = re.fullmatch(
            r"(?:please )?(?:search|find|look for)(?: for)? (.+)",
            text.strip().strip(".!?"), re.IGNORECASE,
        )
        surface = self.current_surface.get(session, "")
        if search and surface.casefold() in {"chrome", "google chrome", "edge", "microsoft edge"}:
            try:
                self.workflows.desktop.search_in_browser(surface.casefold(), search[1])
                self.browser_searches[session] = (surface.casefold(), search[1])
                return f"Asked {surface} to search for {search[1]}."
            except (NishaError, OSError) as exc:
                return f"I couldn't search in {surface}: {exc}"
        reply = self.pc_control.handle(text, current_app=self.current_surface.get(session))
        if reply is not None:
            if reply.startswith(("Clicked ", "Right-clicked ", "Double-clicked ", "Dragged ", "Focused ", "Opened ", "Verified text", "Sent ", "Scrolled ", "Controls in ")):
                explicit = re.search(r" (?:in|on) (.+)$", text, re.IGNORECASE)
                if explicit and not re.fullmatch(
                    r"(?:click|tap|select) (?:on )?the first link",
                    text.strip().strip(".!?"), re.IGNORECASE,
                ):
                    self.current_surface[session] = explicit[1].strip(" .!?")
                    self.system_actions.forget_explorer(session)
            self.store.audit("pc_control", reply[:300])
            return reply
        reply = self.window_actions.handle(text)
        if reply is not None:
            self.system_actions.forget_explorer(session)
            if text.casefold().startswith("close"):
                self.current_surface.pop(session, None)
            self.store.audit("window_action", reply)
            return reply
        self.automation.desktop = self.workflows.desktop
        reply = self.automation.handle(text, session, history, self, alias)
        if reply is None:
            reply = self.workflows.handle(text, session, history, self, alias)
        website_url = self.workflows.last_opened_url if reply is not None else None
        if reply is not None and self.workflows.last_browser_search:
            self.browser_searches[session] = self.workflows.last_browser_search
        if reply is None and session in self.current_surface:
            search = re.fullmatch(
                r"(?:please )?(?:search|find|look for)(?: for)? (.+)",
                text.strip().strip(".!?"),
                re.IGNORECASE,
            )
            if search:
                surface = self.current_surface[session]
                if surface.casefold() == "youtube" and isinstance(self.actions, WebsiteActions):
                    reply = self.actions.handle(
                        f"search {search[1]} on YouTube", history, self.store, session=session
                    )
                    website_url = self.actions.last_url
                elif surface.casefold() in {"chrome", "google chrome", "edge", "microsoft edge"}:
                    try:
                        self.workflows.desktop.search_in_browser(surface.casefold(), search[1])
                        reply = f"Asked {surface} to search for {search[1]}."
                    except (NishaError, OSError) as exc:
                        reply = f"I couldn't search in {surface}: {exc}"
                else:
                    reply = self.pc_control.search(search[1], surface)
        if reply is None and session in self.current_surface:
            opening = re.fullmatch(
                r"(?:please )?(?:open|launch|start) (?:the )?(.+)",
                text.casefold().strip(" .!?"),
            )
            if opening:
                from nisha.actions import WEBSITES, spoken_website

                target = opening[1].strip()
                explicit = (
                    target in WEBSITES
                    or spoken_website(target)
                    or re.search(r"\b(?:app|application|website|site|browser)$", target)
                )
                app_path = getattr(self.workflows.desktop, "app_path", None)
                try:
                    installed = bool(app_path and app_path(target))
                except (NishaError, OSError):
                    installed = False
                if not explicit and not installed:
                    reply = self.pc_control.open_control(target, self.current_surface[session])
        if reply is None:
            self.check_cancelled()
            reply = (
                self.actions.handle(text, history, self.store, session=session)
                if isinstance(self.actions, WebsiteActions)
                else self.actions.handle(text, history, self.store)
            )
            if reply and getattr(self.actions, "last_url", None):
                website_url = self.actions.last_url
                self.automation.remember(
                    session, Step(action="open_website", target=self.actions.last_url)
                )
        if reply is not None:
            if website_url:
                host = (urlparse(website_url).hostname or "").removeprefix("www.")
                self.current_surface[session] = (
                    "YouTube"
                    if "youtube.com" in host
                    else "Gmail"
                    if "mail.google.com" in host
                    else host.split(".")[0]
                )
                self.system_actions.forget_explorer(session)
            elif reply.startswith(("I launched ", "Asked Windows to launch ")):
                opened = re.match(
                    r"(?:please )?(?:open|launch|start) (?:the )?(.+?)(?: app)?$",
                    text.casefold().strip(" .!?"),
                )
                if opened:
                    self.current_surface[session] = opened[1]
                    self.system_actions.forget_explorer(session)
            elif re.match(r"Asked (?:chrome|google chrome|edge|microsoft edge) to search", reply):
                self.current_surface[session] = "chrome" if "chrome" in reply[:20] else "edge"
                self.system_actions.forget_explorer(session)
            elif reply.startswith("Playing ") and reply.endswith(" in Chrome."):
                self.current_surface[session] = "YouTube"
                self.system_actions.forget_explorer(session)
            if re.fullmatch(r"(?:please )?open (?:my |the )?.+ folder", text.casefold().strip(" .!?")):
                recent = self.automation.recent.get(session, [])
                if recent and recent[-1].action == "open_folder" and reply.startswith("Asked Explorer"):
                    from pathlib import Path

                    self.system_actions.explorer_location[session] = Path(recent[-1].target).resolve()
                    self.current_surface[session] = Path(recent[-1].target).name
        return reply

    def background_action(self, text, session, alias="auto", cancelled=None, history=None):
        from nisha.listening import WakeGate
        from nisha.responsiveness import action_request

        text = text.strip()
        if not text or len(text) > 50_000:
            raise ValueError("Enter a message of 1–50000 characters.")
        if not action_request(text) and not self.automation.matches_trigger(text):
            raise ValueError("This request needs the normal conversation path.")
        wake = WakeGate(
            self.settings.voice.wake_word, aliases=self.settings.voice.wake_aliases
        ).pattern.search(text)
        if wake:
            text = text[wake.end() :].strip(" ,.!?:;")
        original = text
        previous = self._cancelled
        self._cancelled = cancelled
        try:
            with self._action_lock:
                self.check_cancelled()
                alias = self.route(session, alias)
                if history is None:
                    _, history = self.store.history(session)
                from nisha.dialogue import resolve_followup, unsupported_action

                text = resolve_followup(text, history)
                with (
                    self.gateway.cancellation(cancelled)
                    if hasattr(self.gateway, "cancellation")
                    else nullcontext()
                ):
                    reply = self.handle_action(text, session, history, alias)
                if reply is None:
                    reply = unsupported_action(text)
                self.check_cancelled()
                self.store.exchange(session, original, reply, cloud_allowed=False)
                self.store.record_outcome(session, original, "response_complete")
                return reply
        except OperationCancelled:
            self.store.record_outcome(session, text, "interrupted")
            raise
        except (NishaError, ValueError) as exc:
            self.store.record_outcome(session, text, "failed", type(exc).__name__)
            raise
        finally:
            self._cancelled = previous

    def learning_command(self, text):
        normalized = text.casefold().strip(" .!?")
        if normalized in {"/reset-preferences", "reset my preferences", "forget my preferences"}:
            self.reinforcement.reset()
            self.learning.forget_learned(categories={"conversation_preference"})
            for item in self.interaction.profile():
                if item["key"] == "profile:personal_preference" and re.search(
                    r"\b(?:answers?|replies|responses?|wording|bullets?|paragraphs?)\b",
                    item["text"],
                    re.IGNORECASE,
                ):
                    self.store.forget(item["id"])
            return self.preferences.handle(text)
        if normalized in {"forget my personal profile", "forget my personal details"}:
            self.learning.forget_learned(categories={"personal_profile", "personal_event"})
            return self.interaction.handle(text)
        if normalized in {"show what you learned", "show conversation learning", "/learning"}:
            memories = [
                m for m in self.store.memories() if m["source"] == "local_conversation_review"
            ]
            return "Learned locally from your conversations:\n" + (
                "\n".join(m["text"] for m in memories) or "No completed reviews yet."
            )
        if normalized in {"forget conversation learning", "forget what you learned from our chats"}:
            self.learning.forget_learned()
            return "Conversation learning cleared locally; queued reviews cancelled."
        return None

    def generate_content(self, text, session, alias, instructions, schema=None):
        self.check_cancelled()
        instructions += " Produce the full requested artifact; response brevity preferences apply to conversational replies, not the artifact."
        preferred = "local_smart" if "local_smart" in self.settings.models else alias
        preferred = self.route(session, preferred)
        messages = self.context.build(session, text, preferred, self.memory.search(text))
        messages.insert(
            1,
            {
                "role": "system",
                "content": instructions,
            },
        )
        try:
            if hasattr(self.gateway, "generate"):
                if schema:
                    result = self.gateway.generate(preferred, messages, schema=schema)
                else:
                    result = self.gateway.generate(preferred, messages)
            else:
                result = self.gateway.complete(preferred, messages)
        except ModelUnavailable:
            if preferred == "local_fast":
                raise
            import logging

            logging.getLogger("nisha").warning(
                "Local writing model unavailable; retrying with local_fast before saving any artifact."
            )
            # Only generation is retried. No draft, app launch or sending action has run.
            messages = self.context.build(session, text, "local_fast", self.memory.search(text))
            messages.insert(1, {"role": "system", "content": instructions})
            if hasattr(self.gateway, "generate"):
                result = self.gateway.generate(
                    "local_fast", messages, **({"schema": schema} if schema else {})
                )
            else:
                result = self.gateway.complete("local_fast", messages)
        self.check_cancelled()
        return result

    def run_task(self, text, alias, approved=False):
        """A future external worker receives only explicitly supplied task text."""
        if not self.settings.external_tasks_enabled:
            raise PrivacyError(
                "External task workers are disabled in this local-only installation."
            )
        if alias not in self.settings.models or self.settings.models[alias].local:
            raise ConfigurationError("Choose a configured external task worker.")
        if not approved:
            raise PrivacyError(
                "Approve sending this specific task text before using an external worker."
            )
        if not text.strip():
            raise ValueError("Task text cannot be empty.")
        from nisha.context import token_bound
        from nisha.errors import ContextTooLarge

        messages = [
            {"role": "system", "content": "Perform the self-contained task in the next message."},
            {"role": "user", "content": text},
        ]
        if token_bound(messages) > self.settings.models[alias].input_budget:
            raise ContextTooLarge("The task is too large for this worker.")
        with self._lock:
            result = self.gateway.complete(alias, messages)
            self.store.save_task(alias, text, result)
            return result
