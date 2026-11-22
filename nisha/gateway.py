"""OpenAI-compatible HTTP adapter. No provider SDK enters NISHA Core."""

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from threading import local

import httpx
import yaml

from nisha.errors import (
    ConfigurationError,
    ContextTooLarge,
    ModelUnavailable,
    OperationCancelled,
    OutputLimitReached,
)
from nisha.settings import Settings


class Gateway:
    def __init__(self, settings: Settings, client: httpx.Client | None = None, services=None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(max(180, settings.request_timeout), connect=5),
            trust_env=False,
        )
        self.owned_client = client is None
        if services is None and self.owned_client:
            from nisha.services import LocalServices

            services = LocalServices(settings)
        self.services = services
        self._thread_state = local()

    @contextmanager
    def cancellation(self, callback):
        previous = getattr(self._thread_state, "cancelled", None)
        self._thread_state.cancelled = callback
        try:
            yield
        finally:
            self._thread_state.cancelled = previous

    @contextmanager
    def response(self, payload):
        cancelled = getattr(self._thread_state, "cancelled", None)
        if self.owned_client and cancelled:
            from nisha.http_stream import cancellable_lines

            lines = cancellable_lines(
                self.settings.gateway_url + "/v1/chat/completions",
                payload,
                self.headers(),
                cancelled,
                max(180, self.settings.request_timeout),
            )
            try:
                yield lines
            finally:
                lines.close()
        else:
            with self.client.stream(
                "POST",
                self.settings.gateway_url + "/v1/chat/completions",
                headers=self.headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                yield response.iter_lines()

    def close(self):
        self.client.close()
        if self.services and hasattr(self.services, "close"):
            self.services.close()

    def headers(self):
        key = os.getenv("NISHA_GATEWAY_KEY", "")
        return {"Authorization": f"Bearer {key}"} if key else {}

    def stream(self, alias, messages, output_tokens=None, response_format=None, temperature=None):
        for attempt in range(2):
            cancelled = getattr(self._thread_state, "cancelled", None)
            if cancelled and cancelled():
                raise OperationCancelled("Operation cancelled.")
            produced = False
            try:
                for chunk in self._stream(
                    alias, messages, output_tokens, response_format, temperature
                ):
                    produced = True
                    yield chunk
                return
            except ModelUnavailable as exc:
                if isinstance(exc, OutputLimitReached):
                    raise  # Normal continuation signal, not a service outage.
                cause = exc.__cause__
                transient = isinstance(cause, httpx.TransportError) or (
                    isinstance(cause, httpx.HTTPStatusError)
                    and cause.response.status_code in {502, 503, 504}
                )
                logging.getLogger("nisha").warning(
                    "Local response failed: %s; http_status=%s; output_started=%s; model=%s.",
                    type(cause).__name__ if cause else type(exc).__name__,
                    cause.response.status_code
                    if isinstance(cause, httpx.HTTPStatusError)
                    else None,
                    produced,
                    alias,
                )
                if (
                    attempt
                    or produced
                    or not transient
                    or not self.services
                    or not self.settings.models[alias].local
                ):
                    raise
                status = (
                    self.services.ensure(cancelled=cancelled)
                    if cancelled
                    else self.services.ensure()
                )
                if cancelled and cancelled():
                    raise OperationCancelled("Operation cancelled.")
                if not status["ready"]:
                    raise ModelUnavailable(
                        "The local engine is still starting or unavailable. Wake listening stays active; I'll keep trying to restore it."
                    ) from exc
                # HTTPX reconnects itself. Replacing this shared client here can
                # close a concurrent background action's metadata request.
                logging.getLogger("nisha").info(
                    "Local services recovered; retrying model generation before any output/action."
                )

    def _stream(
        self,
        alias: str,
        messages: list[dict],
        output_tokens=None,
        response_format=None,
        temperature=None,
    ) -> Iterator[str]:
        profile = self.settings.models[alias]
        try:
            if profile.local:
                metadata = self.client.post(
                    self.settings.ollama_url + "/api/show",
                    json={"model": profile.model.split("/", 1)[1]},
                    timeout=5,
                )
                metadata.raise_for_status()
                details = metadata.json()
                if not isinstance(details, dict) or not isinstance(
                    details.get("model_info", {}), dict
                ):
                    raise ValueError("Invalid local model metadata")
                if (
                    details.get("remote_host")
                    or details.get("remote_model")
                    or not details.get("model_info", {}).get("general.architecture")
                ):
                    raise ModelUnavailable(
                        "This Ollama model is not verified as downloaded local weights."
                    )
            with self.response(
                {
                    "model": alias,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": output_tokens or profile.max_output,
                    **({"response_format": response_format} if response_format else {}),
                    **({"temperature": temperature} if temperature is not None else {}),
                }
            ) as lines:
                completed = False
                for line in lines:
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        completed = True
                        break
                    item = json.loads(raw)
                    if not isinstance(item, dict):
                        raise TypeError("Invalid model stream message")
                    if "error" in item:
                        raise ModelUnavailable(
                            "The model stream failed. Retry or choose another model."
                        )
                    choices = item.get("choices", [])
                    if not isinstance(choices, list) or any(
                        not isinstance(choice, dict) for choice in choices
                    ):
                        raise TypeError("Invalid model stream choices")
                    if choices:
                        delta = choices[0].get("delta", {})
                        if not isinstance(delta, dict):
                            raise TypeError("Invalid model stream delta")
                        content = delta.get("content")
                        if content is not None and not isinstance(content, str):
                            raise TypeError("Invalid model stream content")
                        if content:
                            yield content
                        reason = choices[0].get("finish_reason")
                        if reason == "length":
                            raise OutputLimitReached(
                                "The model reached its output limit before completing this response."
                            )
                        if reason == "content_filter":
                            raise ModelUnavailable("The model declined to complete this response.")
                if not completed:
                    raise ModelUnavailable("The model disconnected before finishing. Please retry.")
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                message = "Model access was rejected. Check gateway and provider keys in .env."
            else:
                message = f"Model service returned HTTP {code}. Check gateway logs or choose a local model."
            raise ModelUnavailable(message) from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # Never display provider response bodies or credentials.
            raise ModelUnavailable(
                "Cannot get a complete model response. Check Ollama and the gateway."
            ) from exc

    def complete(self, alias: str, messages: list[dict]) -> str:
        reply = "".join(self.stream(alias, messages)).strip()
        if not reply:
            raise ModelUnavailable("The model returned no text. Retry or choose another model.")
        return reply

    def respond(self, alias, messages, brief):
        from nisha.context import token_bound

        available = self.settings.models[alias].context_window - token_bound(messages) - 128
        if available < 32:
            raise ContextTooLarge("The local model has no room left to generate this response.")
        return self.continued(alias, messages, output_tokens=min(384 if brief else 1024, available))

    def continued(self, alias, messages, output_tokens, max_parts=8):
        """Continue genuine token-limit stops locally; do not retry broken streams."""
        from nisha.context import token_bound

        base = [dict(message) for message in messages]
        current, answer = base, ""
        for part in range(max_parts):
            available = self.settings.models[alias].context_window - token_bound(current) - 128
            if available < 32:
                raise ContextTooLarge("The local model has no room left to continue this response.")
            pending, limited = [], False
            try:
                for chunk in self.stream(
                    alias, current, output_tokens=min(output_tokens, available)
                ):
                    if part == 0:
                        answer += chunk
                        yield chunk
                    else:
                        pending.append(chunk)
            except OutputLimitReached:
                limited = True
            if part:
                addition = "".join(pending)
                # A model may repeat the previous sentence when asked to continue.
                # Remove only substantial exact suffix/prefix overlap.
                for size in range(min(len(answer), len(addition), 4096), 19, -1):
                    if answer.endswith(addition[:size]):
                        addition = addition[size:]
                        break
                if not addition.strip():
                    raise ModelUnavailable(
                        "The local model could not make progress continuing this response."
                    )
                answer += addition
                yield addition
            if not limited:
                return
            if not answer.strip():
                raise ModelUnavailable(
                    "The local model reached its output limit without returning text."
                )
            if part + 1 == max_parts:
                break
            # Keep all original instructions, request and context. For very long
            # output, retain its beginning and latest ending within the same
            # local context window; the full result still accumulates above.
            budget = (
                self.settings.models[alias].context_window - min(output_tokens, available) - 256
            )
            overhead = token_bound(base + [{"role": "assistant", "content": ""}])
            room = budget - overhead
            if room < 128:
                # Reserve continuation context before reducing the next segment.
                output_tokens = max(32, min(output_tokens, room + output_tokens - 128))
                budget = self.settings.models[alias].context_window - output_tokens - 256
                room = budget - overhead
            if room < 128:
                raise ContextTooLarge(
                    "The local model cannot fit the context needed to continue this response."
                )
            encoded = answer.encode("utf-8")
            if len(encoded) <= room:
                excerpt = answer
            else:
                marker = "\n[Earlier output omitted from this context window; retained locally.]\n"
                prefix_size = min(1024, room // 4)
                tail_size = room - prefix_size - len(marker.encode("utf-8"))
                excerpt = (
                    encoded[:prefix_size].decode("utf-8", errors="ignore")
                    + marker
                    + encoded[-tail_size:].decode("utf-8", errors="ignore")
                )
            # Installed Llama/Qwen Ollama templates leave a final assistant
            # message open. Prefill continues its next token, including a
            # mid-word cut, instead of asking the model to restart an answer.
            current = base + [{"role": "assistant", "content": excerpt}]
        raise ModelUnavailable(
            "The local model reached the continuation limit. The partial response is available on screen; no incomplete artifact was saved."
        )

    def generate(self, alias, messages, schema=None, temperature=None):
        from nisha.context import token_bound

        available = self.settings.models[alias].context_window - token_bound(messages) - 256
        if available < 64:
            raise ContextTooLarge(
                "The writing request is too large. Send a shorter topic or excerpt."
            )
        response_format = (
            {
                "type": "json_schema",
                "json_schema": {"name": "nisha_email_draft", "schema": schema, "strict": True},
            }
            if schema
            else None
        )
        if schema:
            # A constrained JSON response must restart as a whole object. Never
            # splice truncated JSON, save it as a draft, or send it.
            output_tokens = min(2048, available)
            for attempt in range(3):
                try:
                    reply = "".join(
                        self.stream(
                            alias,
                            messages,
                            output_tokens=output_tokens,
                            response_format=response_format,
                            **({"temperature": temperature} if temperature is not None else {}),
                        )
                    ).strip()
                    break
                except OutputLimitReached:
                    if attempt == 2 or output_tokens == available:
                        raise
                    output_tokens = min(output_tokens * 2, available)
        else:
            reply = "".join(
                self.continued(alias, messages, output_tokens=min(2048, available))
            ).strip()
        if not reply:
            raise ModelUnavailable("The writing model returned no content.")
        return reply


def write_gateway_config(settings: Settings):
    """Generate a dedicated gateway with no cross-provider fallback or telemetry hooks."""
    if not os.getenv("NISHA_GATEWAY_KEY"):
        raise ConfigurationError("NISHA_GATEWAY_KEY is missing. Run scripts/setup.ps1.")
    models = []
    for alias, profile in settings.models.items():
        params = {"model": profile.model}
        if profile.local:
            params.update(
                api_base=settings.ollama_url,
                num_ctx=profile.context_window,
                reasoning_effort="none",
                timeout=max(180, settings.request_timeout),
                stream_timeout=max(180, settings.request_timeout),
            )
        models.append({"model_name": alias, "litellm_params": params})
    config = {
        "model_list": models,
        "general_settings": {"master_key": "os.environ/NISHA_GATEWAY_KEY"},
        "litellm_settings": {"request_timeout": settings.request_timeout, "num_retries": 0},
        "router_settings": {"num_retries": 0},
    }
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "litellm.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path
