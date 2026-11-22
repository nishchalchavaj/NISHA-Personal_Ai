# Responsive conversation and background work

NISHA answers exact short greetings and thanks locally, even while the model
services are starting. Other conversation still uses the downloaded local model.
The service worker warms the fast model when no model is resident. It does not
download weights, call a cloud provider, or displace an already loaded model.
When NISHA starts Ollama, it keeps the active model resident for up to one hour
after the last request to reduce cold-load delays after short breaks. An Ollama
server already running outside NISHA keeps its own settings. Keeping a model loaded
uses GPU/CPU memory, and switching models can still require a reload because this
PC is configured to keep one language model loaded at a time.

Generated text streams to the display. Spoken replies currently begin after the
complete response has been generated; microphone recognition and speech playback
have their own latency. A cold PC, a large prompt, switching models, or GPU
contention can still make generated responses slower.

Explicit desktop commands such as opening an app, minimizing windows, writing a
document and turning a configured light on/off use a separate FIFO action worker.
Up to eight commands can wait behind the active action. Conversation remains
available while they run. The input remains enabled and up to eight typed
follow-ups are retained in order, including when the microphone is muted.

Background action acknowledgments and results appear in the conversation panel.
Completed results also appear in the left glass panel when the current reply is
finished. Completion does not speak over an ongoing conversation. Action parsing
uses the conversation history captured when the request was queued. The original
orb layout and the separate conversation/results panels are retained.

Say or type **cancel background tasks** to clear queued actions and request
cancellation of the active action. Completed effects are not reversed. New
conversation requests discard the old action queue and suppress late old-session
results. Closing the app cancels outstanding action and service workers. Stop and
enough continue to interrupt the current response; they are not a rollback of
already completed work.

The local response connection can now be cancelled while waiting for its first
token or between tokens, instead of waiting for the network read timeout. Local
model metadata checks still have a bounded five-second timeout. Adapters may
finish an already issued OS/network request before observing cancellation.

The conversation and action workers have separate locks and thread-local
cancellation. Sharing one GPU still limits true simultaneous model generation:
a long background writing task can compete with a generated spoken reply.
Immediate greeting replies do not need the GPU. This is concurrency at the app
level, not a guarantee of simultaneous GPU throughput.

Gmail sending and YouTube likes/subscriptions retain exact-draft/page review.
Approval commands are not silently queued for later execution. If another action
owns the action worker, NISHA asks for the command again after it finishes.
Only implemented adapters can execute actions; an unsupported request does not
become successful because the language model says so.

Defaults: `instant_smalltalk: true`, `background_actions: true`. Either may be
disabled in configuration for troubleshooting. At first setup on Windows,
NISHA registers a background launch at login so the wake word can open the
window after a reboot. The tray menu's **Start with Windows** control can turn
this off, and later launches respect that choice. The background process still
needs a working default microphone and the user's unlocked Windows session.
External model access remains disabled.

See [reinforcement learning](reinforcement-learning.md) for conversational feedback
and reviewed teacher answers. Every eligible generated conversational turn can
record a learning decision, but only actual feedback changes its reward. Learning
does not run a remote teacher request on every turn.
