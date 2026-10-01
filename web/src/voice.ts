export type VoicePhase = "idle" | "preparing" | "recording" | "transcribing";
export type VoiceCallbacks = {
  begin: () => Promise<number>;
  valid: (epoch: number) => boolean;
  release: (epoch: number) => void;
  submit: (text: string, epoch: number) => Promise<void>;
  update: (phase: VoicePhase, message: string) => void;
};
type Run = {
  abort: AbortController;
  epoch?: number;
  recorder?: MediaRecorder;
  stream?: MediaStream;
  audio?: AudioContext;
  timer?: ReturnType<typeof setTimeout>;
  meter?: ReturnType<typeof setInterval>;
  speechMs: number;
};
/** One deliberate press, one clip, one existing HumanCLI submission. */
export class VoiceCapture {
  run: Run | null = null;
  phase: VoicePhase = "idle";
  constructor(public callbacks: VoiceCallbacks) {}
  private current(run: Run) {
    return (
      this.run === run &&
      !run.abort.signal.aborted &&
      (run.epoch === undefined || this.callbacks.valid(run.epoch))
    );
  }
  private update(phase: VoicePhase, message: string) {
    this.phase = phase;
    this.callbacks.update(phase, message);
  }
  private cleanup(run: Run) {
    clearTimeout(run.timer);
    clearInterval(run.meter);
    if (run.recorder?.state === "recording") run.recorder.stop();
    run.stream?.getTracks().forEach((track) => track.stop());
    if (run.audio && run.audio.state !== "closed")
      void run.audio.close().catch(() => {});
  }
  cancel(message = "Voice cancelled.") {
    const run = this.run;
    if (!run) return;
    this.run = null;
    run.abort.abort();
    this.cleanup(run);
    if (run.epoch !== undefined) this.callbacks.release(run.epoch);
    this.update("idle", message);
  }
  async start() {
    if (this.run) return;
    const run: Run = { abort: new AbortController(), speechMs: 0 };
    this.run = run;
    this.update("preparing", "Pausing movement and opening microphone…");
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === "undefined"
      )
        throw Error("Microphone recording is unavailable in this application.");
      run.epoch = await this.callbacks.begin();
      if (!this.current(run)) {
        this.callbacks.release(run.epoch);
        if (this.run === run) this.cancel();
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      if (!this.current(run)) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      run.stream = stream;
      const mimeType = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw Error("No supported microphone recording format.");
      const recorder = new MediaRecorder(stream, {
        mimeType,
        audioBitsPerSecond: 64000,
      });
      run.recorder = recorder;
      const chunks: Blob[] = [];
      let bytes = 0;
      recorder.ondataavailable = (event) => {
        bytes += event.data.size;
        if (bytes > 2 * 1024 * 1024) {
          this.cancel("Voice clip is too large. Try a shorter phrase.");
          return;
        }
        chunks.push(event.data);
      };
      recorder.onerror = () =>
        this.cancel("Microphone recording failed. Try again.");
      recorder.onstop = () => {
        if (this.current(run))
          void this.send(run, new Blob(chunks, { type: mimeType }));
      };
      stream.getAudioTracks().forEach((track) => {
        track.onended = () => {
          if (this.run === run && this.phase === "recording")
            this.cancel("Microphone disconnected.");
        };
      });
      // Reject silence locally before a speech model can invent an instruction.
      run.audio = new AudioContext();
      await run.audio.resume();
      if (!this.current(run)) return;
      const analyser = run.audio.createAnalyser();
      analyser.fftSize = 2048;
      run.audio.createMediaStreamSource(stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      run.meter = setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(
          samples.reduce((sum, v) => sum + v * v, 0) / samples.length,
        );
        if (rms > 0.012) run.speechMs += 50;
      }, 50);
      recorder.start(250);
      run.timer = setTimeout(
        () =>
          this.cancel(
            "30-second limit reached. Hold R1 for a shorter instruction.",
          ),
        30000,
      );
      this.update(
        "recording",
        "Listening… Release to send. B or Escape cancels.",
      );
    } catch (error) {
      if (this.run === run)
        this.cancel(
          error instanceof Error ? error.message : "Could not open microphone.",
        );
    }
  }
  finish() {
    const run = this.run;
    if (!run) return;
    if (this.phase === "preparing") {
      this.cancel("Microphone was not ready. Hold to talk again.");
      return;
    }
    if (this.phase !== "recording") return;
    if (!this.current(run)) {
      this.cancel();
      return;
    }
    if (run.speechMs < 200) {
      this.cancel(
        "No speech detected. Hold to talk and speak near the microphone.",
      );
      return;
    }
    this.update("transcribing", "Transcribing with OpenAI…");
    this.cleanup(run);
  }
  private async send(run: Run, audio: Blob) {
    if (!this.current(run) || this.phase !== "transcribing") return;
    run.timer = setTimeout(() => {
      if (this.run === run) this.cancel("Transcription timed out. Try again.");
    }, 55000);
    try {
      const response = await fetch(`/api/agent/transcribe?epoch=${run.epoch}`, {
        method: "POST",
        headers: { "X-Go2-Request": "1", "Content-Type": audio.type },
        body: audio,
        signal: run.abort.signal,
      });
      const result = await response.json();
      if (!response.ok)
        throw Error(
          typeof result.detail === "string"
            ? result.detail
            : "Transcription failed.",
        );
      if (!this.current(run) || document.hidden || !document.hasFocus()) {
        if (this.run === run) this.cancel();
        return;
      }
      if (typeof result.text !== "string" || !result.text.trim())
        throw Error("No speech recognized.");
      await this.callbacks.submit(result.text, run.epoch!);
      if (this.run !== run) return;
      this.run = null;
      clearTimeout(run.timer);
      this.update("idle", "Instruction sent to HumanCLI.");
    } catch (error) {
      if (this.run === run)
        this.cancel(error instanceof Error ? error.message : "Voice failed.");
    }
  }
}
