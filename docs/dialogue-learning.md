# Local dialogue and learning

NISHA uses the installed Whisper model for speech recognition and local Ollama
models for generated language. The fast model handles ordinary conversation;
the smart model is available for more demanding local work. No external model is
the base assistant.

The dialogue path keeps recent turns and a bounded local summary. Short action
follow-ups such as “Open” resolve only to a nearby named target. PC commands
are routed to action handlers and cannot become free-form claims of success.
Windows requests report what was observed; shutdown and Recycle Bin emptying
require a one-use confirmation bound to the current conversation. Direct
requests for silence stop speech without a spoken acknowledgement.

After a conversation, a separate local reviewer proposes memories from user
statements. Every accepted memory must contain an exact quote from that user's
input. Unverifiable proposals are discarded without blocking verified items in
the same batch. Malformed model responses remain queued for retry. Explicit
user feedback also updates a local response-style reward policy. This is
inference, retrieval and preference learning. A small local answer presentation
neural reward model can train its own weights after enough explicit ratings; the
Llama/Qwen language-model weights are not fine-tuned.

The model can still misunderstand speech or generate an awkward reply. The
saved-audio and automated checks do not establish performance after a reboot
or in every room-noise condition; live feedback and correction remain useful.
