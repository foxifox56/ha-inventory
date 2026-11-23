import test from 'node:test';
import assert from 'node:assert/strict';
import { startZXingScanner } from '../zxing-scanner.mjs';

test('scanner prefers the rear camera and stops as soon as a barcode is read', async () => {
  const video = {};
  let receivedConstraints;
  let receivedVideo;
  let stopCount = 0;
  let barcode;
  const controls = { stop: () => { stopCount += 1; } };
  const reader = {
    async decodeFromConstraints(constraints, target, callback) {
      receivedConstraints = constraints;
      receivedVideo = target;
      callback({ getText: () => '00012345' }, undefined, controls);
      return controls;
    },
  };

  const scan = await startZXingScanner(reader, video, (value) => { barcode = value; });
  assert.deepEqual(receivedConstraints, {
    video: { facingMode: { ideal: 'environment' } },
    audio: false,
  });
  assert.equal(receivedVideo, video);
  assert.equal(barcode, '00012345');
  assert.equal(stopCount, 1);
  scan.stop();
  assert.equal(stopCount, 1);
});

test('not-found frames are ignored while camera errors are reported', async () => {
  let reportError;
  const reader = {
    async decodeFromConstraints(_constraints, _video, callback) {
      callback(undefined, { name: 'NotFoundException' }, {});
      callback(undefined, { name: 'NotAllowedError' }, {});
      return { stop() {} };
    },
  };
  await startZXingScanner(reader, {}, () => assert.fail('no code was decoded'), (error) => { reportError = error.name; });
  assert.equal(reportError, 'NotAllowedError');
});
