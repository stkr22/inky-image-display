# Changelog

## [3.0.0](https://github.com/stkr22/inky-image-display/compare/controller-v2.2.1...controller-v3.0.0) (2026-05-15)


### ⚠ BREAKING CHANGES

* ``DisplayInfo`` removed; ``DeviceRegistration`` reshaped; ``Device`` and both job models swap their spec / ``target_device_id`` fields for FKs to ``device_profiles``. Controllers must upgrade with the API.

### Features

* introduce device profiles to replace per-device hardware specs ([1268bbe](https://github.com/stkr22/inky-image-display/commit/1268bbe592b6fb6d92697b04ea09df1557582a5d))


### Bug Fixes

* **deps:** bump inky-image-display-shared pin to ~=3.0 ([b49cc93](https://github.com/stkr22/inky-image-display/commit/b49cc9394cf08cb63e16b096019e3f0ea3c261bc))

## [2.2.1](https://github.com/stkr22/inky-image-display/compare/controller-v2.2.0...controller-v2.2.1) (2026-05-13)


### Bug Fixes

* **deps:** require inky-image-display-shared ~=2.2 across packages ([61969a8](https://github.com/stkr22/inky-image-display/commit/61969a8e0dda3cec7de5d615f4a386258dab65dc))

## [2.2.0](https://github.com/stkr22/inky-image-display/compare/controller-v2.1.0...controller-v2.2.0) (2026-05-12)


### Features

* **controller:** centralize MQTT/S3 settings via registration response ([c030539](https://github.com/stkr22/inky-image-display/commit/c0305392c739f90bbc53733585932bcf0f25d7d1))
* **controller:** centralize MQTT/S3 settings via registration response ([b8c4c26](https://github.com/stkr22/inky-image-display/commit/b8c4c26d82877c816c7dd4e50f7021e270cc8d14))

## [2.1.0](https://github.com/stkr22/inky-image-display/compare/controller-v2.0.0...controller-v2.1.0) (2026-05-04)


### Features

* **mqtt:** :sparkles: support MQTT-over-WebSockets transport ([ebdeb53](https://github.com/stkr22/inky-image-display/commit/ebdeb53449877985ee40ec3bd4a74547d1bf7e12))
* **mqtt:** :sparkles: support MQTT-over-WebSockets transport ([7ea0154](https://github.com/stkr22/inky-image-display/commit/7ea0154e04159a8b020416880f72786b48fbc75a))


### Bug Fixes

* **controller:** :pushpin: tighten inky-image-display-shared pin ([4d339aa](https://github.com/stkr22/inky-image-display/commit/4d339aa535469fc4b4e1f62c704bc960fd1a26c8))
* **controller:** :pushpin: tighten inky-image-display-shared pin ([0fb8be7](https://github.com/stkr22/inky-image-display/commit/0fb8be7852df4dff2c14b2986054ebc5941ea778))

## [2.0.0](https://github.com/stkr22/inky-image-display/compare/controller-v1.0.3...controller-v2.0.0) (2026-05-04)


### ⚠ BREAKING CHANGES

* Devices and the API now require an MQTT broker. The /ws/devices/{id} WebSocket endpoint is removed; devices must call POST /api/devices/register over HTTP and connect to the broker. Controller env vars now require a CONTROLLER_ prefix (e.g. CONTROLLER_DEVICE__ID instead of DEVICE__ID); controller's API URL is HTTP not ws://. New required API setting: API_MQTT_HOST.

### Features

* :sparkles: replace device websocket transport with mqtt ([8d4fdcb](https://github.com/stkr22/inky-image-display/commit/8d4fdcbf3bf5981de675673eb25fb50fada46444))

## [1.0.3](https://github.com/stkr22/inky-image-display/compare/controller-v1.0.2...controller-v1.0.3) (2026-04-30)


### Bug Fixes

* **ws:** :bug: prevent stale-disconnect from clobbering live reconnects ([ebebfb6](https://github.com/stkr22/inky-image-display/commit/ebebfb631b4b4064acb3cb64b056a43a95ab315a))
* **ws:** :bug: prevent stale-disconnect from clobbering live reconnects ([1c7e285](https://github.com/stkr22/inky-image-display/commit/1c7e285f7c7bac00e2e76e919c479f2f740b29b7))

## [1.0.2](https://github.com/stkr22/inky-image-display/compare/controller-v1.0.1...controller-v1.0.2) (2026-04-26)


### Bug Fixes

* **controller:** :bug: bound MinIO HTTP timeouts ([e49d62a](https://github.com/stkr22/inky-image-display/commit/e49d62ae430e8c34eedeb11cc20e79889c44d619))
* **controller:** :bug: bound MinIO HTTP timeouts ([c4c423b](https://github.com/stkr22/inky-image-display/commit/c4c423bb35a477bbe392116f13e10f46204aafee))

## [1.0.1](https://github.com/stkr22/inky-image-display/compare/controller-v1.0.0...controller-v1.0.1) (2026-04-18)


### Bug Fixes

* :bug: pin inky-image-display-shared&gt;=0.3.0 in controller ([b852249](https://github.com/stkr22/inky-image-display/commit/b85224984b228fc4d2f5050ac48be783a998a471))
* :bug: pin inky-image-display-shared&gt;=0.3.0 in controller ([e6fdabe](https://github.com/stkr22/inky-image-display/commit/e6fdabe267f22b52a8d5445bf54e2a63e5f9176f))

## [1.0.0](https://github.com/stkr22/inky-image-display/compare/controller-v0.17.0...controller-v1.0.0) (2026-04-18)


### ⚠ BREAKING CHANGES

* drop support for python 3.12 and add python 3.14 support

### Features

* drop support for python 3.12 and add python 3.14 support ([e25fef7](https://github.com/stkr22/inky-image-display/commit/e25fef734d435a45734189ad0192840c658c62fd))
* drop support for python 3.12 and add python 3.14 support ([fbc18e0](https://github.com/stkr22/inky-image-display/commit/fbc18e090c8f19a125aad99c034407a9c4281f3b))


### Bug Fixes

* :bug: resolve websocket test hang with NullPool and temp-file SQLite ([38b2f60](https://github.com/stkr22/inky-image-display/commit/38b2f607efc320c3ad74a5c5b49cd139ec5b8d8d))

## [0.17.0](https://github.com/stkr22/inky-image-display/compare/controller-v0.16.0...controller-v0.17.0) (2026-04-18)


### Features

* :sparkles: add shared rich logging and fix sync service silent failures ([7b77ff3](https://github.com/stkr22/inky-image-display/commit/7b77ff30a7e97cc6fde52a7478e9b8e07e924735))

## [0.16.0](https://github.com/stkr22/inky-image-display/compare/controller-v0.15.0...controller-v0.16.0) (2026-04-16)


### Features

* :sparkles: add GET /health endpoint to api service ([1c05a87](https://github.com/stkr22/inky-image-display/commit/1c05a8711fbc8e94071f4692a3419190155baa27))
* :sparkles: add GET /health endpoint to api service ([479afb3](https://github.com/stkr22/inky-image-display/commit/479afb3a999f94753a19522ff7aeab35f71f59d9))

## [0.15.0](https://github.com/stkr22/inky-image-display/compare/controller-v0.14.0...controller-v0.15.0) (2026-04-16)


### Features

* :sparkles: add Inky display controller for Raspberry Pi ([bdb2752](https://github.com/stkr22/inky-image-display/commit/bdb27522529897129a36733b47960f0faea93198))
