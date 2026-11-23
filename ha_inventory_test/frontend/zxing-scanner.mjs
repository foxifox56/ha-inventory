const CAMERA_CONSTRAINTS = Object.freeze({
  video: { facingMode: { ideal: 'environment' } },
  audio: false,
});

/** Start a ZXing browser reader with the rear-facing camera preferred. */
export async function startZXingScanner(reader, video, onBarcode, onError = () => {}) {
  let stopped = false;
  let controls;
  let controlsStopped = false;
  const stopControls = (target = controls) => {
    if (!target || controlsStopped) return;
    controlsStopped = true;
    target.stop();
  };
  const stop = () => {
    stopped = true;
    stopControls();
  };

  controls = await reader.decodeFromConstraints(
    CAMERA_CONSTRAINTS,
    video,
    (result, error, callbackControls) => {
      if (stopped) return;
      if (result) {
        stopped = true;
        stopControls(callbackControls);
        onBarcode(result.getText());
      } else if (error && error.name !== 'NotFoundException') {
        onError(error);
      }
    },
  );
  if (stopped) stopControls();
  return { stop };
}
