/* The phone's microphone: an AudioWorkletProcessor that hands every input block to the
 * page as a copy (Float32Array, mono, the context's sample rate). The page keeps a short
 * ring while idle and collects while the target is held; nothing is kept here. Loaded with
 * audioWorklet.addModule("/rec.js") by debug.js (the phone-microphone switch) and by the old
 * face's fish.js, in browser capture mode only. */
class FishRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length) {
      this.port.postMessage(new Float32Array(input[0]));
    }
    return true;                         // keep the node alive while the stream lives
  }
}
registerProcessor("fish-rec", FishRecorder);
