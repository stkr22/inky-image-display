# Changelog

## [3.1.0](https://github.com/stkr22/inky-image-display/compare/shared-v3.0.0...shared-v3.1.0) (2026-05-16)


### Features

* add grids for shared display across multiple Inky panels ([3b8db42](https://github.com/stkr22/inky-image-display/commit/3b8db423fd518edc1f49b80a697b1c4aad124385))
* add grids for shared display across multiple Inky panels ([a1d9fde](https://github.com/stkr22/inky-image-display/commit/a1d9fdedb3fb811c0c8e42b1da89e58ab22fd685))

## [3.0.0](https://github.com/stkr22/inky-image-display/compare/shared-v2.2.0...shared-v3.0.0) (2026-05-15)


### ⚠ BREAKING CHANGES

* ``DisplayInfo`` removed; ``DeviceRegistration`` reshaped; ``Device`` and both job models swap their spec / ``target_device_id`` fields for FKs to ``device_profiles``. Controllers must upgrade with the API.

### Features

* introduce device profiles to replace per-device hardware specs ([1268bbe](https://github.com/stkr22/inky-image-display/commit/1268bbe592b6fb6d92697b04ea09df1557582a5d))

## [2.2.0](https://github.com/stkr22/inky-image-display/compare/shared-v2.1.0...shared-v2.2.0) (2026-05-12)


### Features

* **genai:** add AI image generation with editable prompts and on-demand UI ([4344cf2](https://github.com/stkr22/inky-image-display/commit/4344cf2d03c2c3f7c1c5137fcd7f33f56945ddaf))
* **genai:** add AI image generation with editable prompts and on-demand UI ([3168737](https://github.com/stkr22/inky-image-display/commit/3168737d7fdc509bd016abe43c5daba54c7251f7))

## [2.1.0](https://github.com/stkr22/inky-image-display/compare/shared-v2.0.1...shared-v2.1.0) (2026-05-12)


### Features

* **controller:** centralize MQTT/S3 settings via registration response ([c030539](https://github.com/stkr22/inky-image-display/commit/c0305392c739f90bbc53733585932bcf0f25d7d1))
* **controller:** centralize MQTT/S3 settings via registration response ([b8c4c26](https://github.com/stkr22/inky-image-display/commit/b8c4c26d82877c816c7dd4e50f7021e270cc8d14))

## [2.0.1](https://github.com/stkr22/inky-image-display/compare/shared-v2.0.0...shared-v2.0.1) (2026-05-05)


### Bug Fixes

* **api:** :bug: trust mqtt-driven is_online flag instead of last_seen freshness ([063c459](https://github.com/stkr22/inky-image-display/commit/063c459083c0cbcace248961156f0029acbc5773))
* **api:** :bug: trust mqtt-driven is_online flag instead of last_seen freshness ([d824cf2](https://github.com/stkr22/inky-image-display/commit/d824cf25337fc9873c2ad0e5cbe8aeecf898e56b))

## [2.0.0](https://github.com/stkr22/inky-image-display/compare/shared-v1.1.1...shared-v2.0.0) (2026-05-04)


### ⚠ BREAKING CHANGES

* Devices and the API now require an MQTT broker. The /ws/devices/{id} WebSocket endpoint is removed; devices must call POST /api/devices/register over HTTP and connect to the broker. Controller env vars now require a CONTROLLER_ prefix (e.g. CONTROLLER_DEVICE__ID instead of DEVICE__ID); controller's API URL is HTTP not ws://. New required API setting: API_MQTT_HOST.

### Features

* :sparkles: replace device websocket transport with mqtt ([8d4fdcb](https://github.com/stkr22/inky-image-display/commit/8d4fdcbf3bf5981de675673eb25fb50fada46444))

## [1.1.1](https://github.com/stkr22/inky-image-display/compare/shared-v1.1.0...shared-v1.1.1) (2026-04-30)


### Bug Fixes

* **ws:** :bug: prevent stale-disconnect from clobbering live reconnects ([ebebfb6](https://github.com/stkr22/inky-image-display/commit/ebebfb631b4b4064acb3cb64b056a43a95ab315a))
* **ws:** :bug: prevent stale-disconnect from clobbering live reconnects ([1c7e285](https://github.com/stkr22/inky-image-display/commit/1c7e285f7c7bac00e2e76e919c479f2f740b29b7))

## [1.1.0](https://github.com/stkr22/inky-image-display/compare/shared-v1.0.0...shared-v1.1.0) (2026-04-21)


### Features

* **sync:** :sparkles: track source_id and sync_job_name on images ([dff583b](https://github.com/stkr22/inky-image-display/commit/dff583b3195593bf38a5d3a0797b2437a8410524))

## [1.0.0](https://github.com/stkr22/inky-image-display/compare/shared-v0.3.0...shared-v1.0.0) (2026-04-18)


### ⚠ BREAKING CHANGES

* drop support for python 3.12 and add python 3.14 support

### Features

* drop support for python 3.12 and add python 3.14 support ([e25fef7](https://github.com/stkr22/inky-image-display/commit/e25fef734d435a45734189ad0192840c658c62fd))
* drop support for python 3.12 and add python 3.14 support ([fbc18e0](https://github.com/stkr22/inky-image-display/commit/fbc18e090c8f19a125aad99c034407a9c4281f3b))

## [0.3.0](https://github.com/stkr22/inky-image-display/compare/shared-v0.2.0...shared-v0.3.0) (2026-04-18)


### Features

* :sparkles: add shared rich logging and fix sync service silent failures ([7b77ff3](https://github.com/stkr22/inky-image-display/commit/7b77ff30a7e97cc6fde52a7478e9b8e07e924735))

## [0.2.0](https://github.com/stkr22/inky-image-display/compare/shared-v0.1.0...shared-v0.2.0) (2026-04-17)


### Features

* :sparkles: add shared SQLModel models and Pydantic schemas ([5351760](https://github.com/stkr22/inky-image-display/commit/53517604edc3d627b3c2e46bc842215f26f6a277))
* :sparkles: publish inky-image-display-shared to PyPI ([bb97fab](https://github.com/stkr22/inky-image-display/commit/bb97fab28a4ae5458bc6a4f58f88823dfbb44dd6))
* :sparkles: publish inky-image-display-shared to PyPI ([1eaa8e8](https://github.com/stkr22/inky-image-display/commit/1eaa8e86a3d02a827c43693f1daeae3138cd6ed0))
