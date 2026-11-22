# Personal voice enrollment

Open NISHA and press **Ctrl+R**, choose **Personal voice samples** in the tray,
or type `/voice-samples`. The original dashboard is unchanged.

The recorder defaults to the Windows system microphone. A fixed choice isolates that
microphone; each take keeps the chosen input throughout the recording.
Click Record, wait for **Recording now**, say the phrase once, then listen to the take.
Correct **Exact words spoken** to what you actually said, and click Save.
Discarded takes remain in memory only. Imported recordings must be mono, 16 kHz,
16-bit PCM WAV. No enrollment recording is uploaded.

Start with these samples:

- 20 standalone wake takes: alternate **NISHA** and **Hey NISHA**, at your normal
  pace, a little slower/faster, and different distances from the microphone.
- 20 short non-wake speech takes: ordinary phrases, similar-sounding words, and
  commands without NISHA. These help test accidental activation.
- At least 30 varied command/conversation takes to measure transcription accuracy:
  open YouTube, open a less common site, open my project folder, write in Notepad,
  draft an email, write Python code, answer briefly, explain in detail, and your
  own typical requests. Keep exact transcripts, including your usual accent and wording.

**Train and test personal wake model** builds a small local MFCC/DTW template
classifier from your wake recordings. It uses separate training, calibration and
test clips; it activates only if all held-out wake clips pass and no held-out
non-wake clip triggers it. The previous model remains active after failed training.
**Train and test neural wake model** trains a two-hidden-layer neural network on
the same reviewed recordings. It saves learned weights separately and becomes the
live detector only after its held-out wake and non-wake checks pass. When active,
the listener reloads it automatically; otherwise it continues using the existing
MFCC/DTW model. The neural report is saved as `neural-training-report.json`.
Command recordings without a wake prefix also provide non-wake examples. Noisy or
silent recording padding is removed from the training features; the original WAVs and
reviewed transcripts stay unchanged. Save more variations whenever you want, then click
the same training button to include them. Enrollment can grow beyond 100 recordings;
the active model uses at most 100 fitted templates to bound wake-detection work.
With only 10 positive/negative samples, the held-out tests are small: collect more
and verify in your actual room. Passing them does not guarantee live accuracy.
The listener reloads a successful model automatically. Use a standalone wake,
pause briefly, then speak your command. Combined wake/commands still use Whisper.

The personal wake classifier does **not** fine-tune Whisper or the conversation model.
Command clips and transcripts form a local dataset for evaluating ASR first, then
planning supervised Whisper adaptation if the remaining errors justify it. A few
wake recordings cannot teach natural command transcription or conversation by themselves.
All files are under `E:\NISHA\data\voice-profile`, excluded from Git.

For local diagnostics:

```powershell
.\.venv\Scripts\python.exe scripts\voice_profile.py status
.\.venv\Scripts\python.exe scripts\voice_profile.py train
.\.venv\Scripts\python.exe scripts\voice_profile.py train-neural
.\.venv\Scripts\python.exe scripts\voice_profile.py evaluate
```

Evaluation saves an exact transcript comparison and word error rate locally;
it performs no PC actions. Stop NISHA first if GPU memory is tight, since evaluation
loads another copy of the cached speech model. Training the small wake classifier
uses only CPU and needs no network/model download.

Live ASR runs in an isolated local process with a 20-second decoding deadline;
stalled inference is discarded, the worker is terminated and the next utterance
restarts it. Model initialization has a 60-second deadline. Transcript text and
raw background audio are not written to diagnostic logs; they contain timing and
confidence flags. Uncertain commands still require confirmation, even when the
wake prefix is clear. Manual launch/tray opening starts a fresh visible conversation;
previous chats and learned preferences remain stored locally.

Background audio continues to be discarded rather than collected as training data.

On this PC, the October 7 training used 11 reviewed wake recordings and 60 non-wake
examples (24 negatives plus 36 commands without a wake prefix). The model activated
after both held-out wakes passed and none of 12 held-out non-wake takes triggered it.
These are small held-out tests, not a guarantee of microphone accuracy in daily use.
All 71 original recordings remain saved. The detailed local report is
`E:\NISHA\data\voice-profile\training-report.json`.

Reference approaches: [Rhasspy's personal template wake detection](https://rhasspy.readthedocs.io/en/latest/wake-word/#raven)
and [Hugging Face's supervised Whisper fine-tuning guide](https://huggingface.co/blog/fine-tune-whisper).
NISHA's small wake classifier is its own implementation, not an installed Raven service.
