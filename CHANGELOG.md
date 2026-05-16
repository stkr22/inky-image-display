# Changelog

## [4.1.0](https://github.com/stkr22/inky-image-display/compare/v4.0.0...v4.1.0) (2026-05-16)


### Features

* add grids for shared display across multiple Inky panels ([3b8db42](https://github.com/stkr22/inky-image-display/commit/3b8db423fd518edc1f49b80a697b1c4aad124385))
* add grids for shared display across multiple Inky panels ([a1d9fde](https://github.com/stkr22/inky-image-display/commit/a1d9fdedb3fb811c0c8e42b1da89e58ab22fd685))

## [4.0.0](https://github.com/stkr22/inky-image-display/compare/v3.0.2...v4.0.0) (2026-05-15)


### ⚠ BREAKING CHANGES

* ``DisplayInfo`` removed; ``DeviceRegistration`` reshaped; ``Device`` and both job models swap their spec / ``target_device_id`` fields for FKs to ``device_profiles``. Controllers must upgrade with the API.

### Features

* introduce device profiles to replace per-device hardware specs ([1268bbe](https://github.com/stkr22/inky-image-display/commit/1268bbe592b6fb6d92697b04ea09df1557582a5d))


### Bug Fixes

* **deps:** bump inky-image-display-shared pin to ~=3.0 ([b49cc93](https://github.com/stkr22/inky-image-display/commit/b49cc9394cf08cb63e16b096019e3f0ea3c261bc))


### Documentation

* reflect device profiles in main/configuration/ui guides ([86d8cbe](https://github.com/stkr22/inky-image-display/commit/86d8cbe92101fc576d936c49b901066aa7a32dcc))

## [3.0.2](https://github.com/stkr22/inky-image-display/compare/v3.0.1...v3.0.2) (2026-05-13)


### Bug Fixes

* **api:** avoid expired ORM attribute access in generation background task ([a1c671a](https://github.com/stkr22/inky-image-display/commit/a1c671a23b53d47bcf3071f0107665fa93520b08))
* **api:** avoid expired ORM attribute access in generation background task ([695edd8](https://github.com/stkr22/inky-image-display/commit/695edd8809662453eb47a8f423c33b70882ba45b))

## [3.0.1](https://github.com/stkr22/inky-image-display/compare/v3.0.0...v3.0.1) (2026-05-13)


### Bug Fixes

* **api:** repair seeded prompt-preset UUIDs unreachable by ORM on SQLite ([b2518d9](https://github.com/stkr22/inky-image-display/commit/b2518d9bba98f7b31a204f254e784a96a90167eb))
* **api:** repair seeded prompt-preset UUIDs unreachable by ORM on SQLite ([210fa1f](https://github.com/stkr22/inky-image-display/commit/210fa1f798d14c768d6a67853942c0e6a50d5942))

## [3.0.0](https://github.com/stkr22/inky-image-display/compare/v2.4.1...v3.0.0) (2026-05-13)


### ⚠ BREAKING CHANGES

* **api:** API_DEVICE_MQTT_HOST is now required.

### Features

* **api:** split MQTT settings between API and controller-facing ([ad315a5](https://github.com/stkr22/inky-image-display/commit/ad315a545e40dec09c411137c5f14a528d424856))


### Bug Fixes

* **deps:** require inky-image-display-shared ~=2.2 across packages ([61969a8](https://github.com/stkr22/inky-image-display/commit/61969a8e0dda3cec7de5d615f4a386258dab65dc))

## [2.4.1](https://github.com/stkr22/inky-image-display/compare/v2.4.0...v2.4.1) (2026-05-13)


### Bug Fixes

* **api:** avoid lazy load on expired ORM attributes in rotation log session.commit() in update_display_state expires instance attributes by ([af7ebb0](https://github.com/stkr22/inky-image-display/commit/af7ebb03d7ff6d017f0b1a8f706f8d7a9dae1267))
* **api:** avoid lazy load on expired ORM attributes in rotation log session.commit() in update_display_state expires instance attributes by ([afca7e9](https://github.com/stkr22/inky-image-display/commit/afca7e9b624ad255ae264d4a16d386a21af9ed6f))


### Documentation

* cover the new GenAI surface (api, ui, deployment, config) ([206c119](https://github.com/stkr22/inky-image-display/commit/206c1196d8c4c660d94cac41cd571a523f35d2b6))
* cover the new GenAI surface (api, ui, deployment, config) ([b82e06f](https://github.com/stkr22/inky-image-display/commit/b82e06f649647151f9559578c978b0d1a6e6ddba))

## [2.4.0](https://github.com/stkr22/inky-image-display/compare/v2.3.0...v2.4.0) (2026-05-12)


### Features

* **genai:** add AI image generation with editable prompts and on-demand UI ([4344cf2](https://github.com/stkr22/inky-image-display/commit/4344cf2d03c2c3f7c1c5137fcd7f33f56945ddaf))
* **genai:** add AI image generation with editable prompts and on-demand UI ([3168737](https://github.com/stkr22/inky-image-display/commit/3168737d7fdc509bd016abe43c5daba54c7251f7))

## [2.3.0](https://github.com/stkr22/inky-image-display/compare/v2.2.0...v2.3.0) (2026-05-12)


### Features

* **controller:** centralize MQTT/S3 settings via registration response ([c030539](https://github.com/stkr22/inky-image-display/commit/c0305392c739f90bbc53733585932bcf0f25d7d1))
* **controller:** centralize MQTT/S3 settings via registration response ([b8c4c26](https://github.com/stkr22/inky-image-display/commit/b8c4c26d82877c816c7dd4e50f7021e270cc8d14))

## [2.2.0](https://github.com/stkr22/inky-image-display/compare/v2.1.1...v2.2.0) (2026-05-12)


### Features

* **ui:** :sparkles: light-minimal bento redesign with hero landing page ([b530123](https://github.com/stkr22/inky-image-display/commit/b530123684d88a9d0e83e8d893c5a80962b64846))
* **ui:** :sparkles: light-minimal bento redesign with hero landing page ([5283799](https://github.com/stkr22/inky-image-display/commit/5283799db71e0a932467ef636592a3cd3acfbd17))

## [2.1.1](https://github.com/stkr22/inky-image-display/compare/v2.1.0...v2.1.1) (2026-05-05)


### Bug Fixes

* **api:** :bug: trust mqtt-driven is_online flag instead of last_seen freshness ([063c459](https://github.com/stkr22/inky-image-display/commit/063c459083c0cbcace248961156f0029acbc5773))
* **api:** :bug: trust mqtt-driven is_online flag instead of last_seen freshness ([d824cf2](https://github.com/stkr22/inky-image-display/commit/d824cf25337fc9873c2ad0e5cbe8aeecf898e56b))

## [2.1.0](https://github.com/stkr22/inky-image-display/compare/v2.0.0...v2.1.0) (2026-05-04)


### Features

* **mqtt:** :sparkles: support MQTT-over-WebSockets transport ([ebdeb53](https://github.com/stkr22/inky-image-display/commit/ebdeb53449877985ee40ec3bd4a74547d1bf7e12))
* **mqtt:** :sparkles: support MQTT-over-WebSockets transport ([7ea0154](https://github.com/stkr22/inky-image-display/commit/7ea0154e04159a8b020416880f72786b48fbc75a))


### Bug Fixes

* **controller:** :pushpin: tighten inky-image-display-shared pin ([4d339aa](https://github.com/stkr22/inky-image-display/commit/4d339aa535469fc4b4e1f62c704bc960fd1a26c8))
* **controller:** :pushpin: tighten inky-image-display-shared pin ([0fb8be7](https://github.com/stkr22/inky-image-display/commit/0fb8be7852df4dff2c14b2986054ebc5941ea778))

## [2.0.0](https://github.com/stkr22/inky-image-display/compare/v1.3.2...v2.0.0) (2026-05-04)


### ⚠ BREAKING CHANGES

* Devices and the API now require an MQTT broker. The /ws/devices/{id} WebSocket endpoint is removed; devices must call POST /api/devices/register over HTTP and connect to the broker. Controller env vars now require a CONTROLLER_ prefix (e.g. CONTROLLER_DEVICE__ID instead of DEVICE__ID); controller's API URL is HTTP not ws://. New required API setting: API_MQTT_HOST.

### Features

* :sparkles: replace device websocket transport with mqtt ([8d4fdcb](https://github.com/stkr22/inky-image-display/commit/8d4fdcbf3bf5981de675673eb25fb50fada46444))

## [1.3.2](https://github.com/stkr22/inky-image-display/compare/v1.3.1...v1.3.2) (2026-04-30)


### Bug Fixes

* **ws:** :bug: stop kicking previous socket on connect ([1a2eea1](https://github.com/stkr22/inky-image-display/commit/1a2eea1a35e2e0d032182c4d64a390cf88dbc010))
* **ws:** :bug: stop kicking previous socket on connect ([d862fd7](https://github.com/stkr22/inky-image-display/commit/d862fd780a7798a02a399d321a94c906d4898500))

## [1.3.1](https://github.com/stkr22/inky-image-display/compare/v1.3.0...v1.3.1) (2026-04-30)


### Bug Fixes

* **ws:** :bug: prevent stale-disconnect from clobbering live reconnects ([ebebfb6](https://github.com/stkr22/inky-image-display/commit/ebebfb631b4b4064acb3cb64b056a43a95ab315a))
* **ws:** :bug: prevent stale-disconnect from clobbering live reconnects ([1c7e285](https://github.com/stkr22/inky-image-display/commit/1c7e285f7c7bac00e2e76e919c479f2f740b29b7))

## [1.3.0](https://github.com/stkr22/inky-image-display/compare/v1.2.5...v1.3.0) (2026-04-28)


### Features

* **ui:** :sparkles: rewrite UI from Flet to NiceGUI ([e33e328](https://github.com/stkr22/inky-image-display/commit/e33e328964e8c96bcc8d75c92f8b42076e849ca1))
* **ui:** :sparkles: rewrite UI from Flet to NiceGUI ([d564606](https://github.com/stkr22/inky-image-display/commit/d5646069dfcb20f7520d0fb37e451d44514d8e5a))

## [1.2.5](https://github.com/stkr22/inky-image-display/compare/v1.2.4...v1.2.5) (2026-04-26)


### Bug Fixes

* **controller:** :bug: bound MinIO HTTP timeouts ([e49d62a](https://github.com/stkr22/inky-image-display/commit/e49d62ae430e8c34eedeb11cc20e79889c44d619))
* **controller:** :bug: bound MinIO HTTP timeouts ([c4c423b](https://github.com/stkr22/inky-image-display/commit/c4c423bb35a477bbe392116f13e10f46204aafee))

## [1.2.4](https://github.com/stkr22/inky-image-display/compare/v1.2.3...v1.2.4) (2026-04-23)


### Bug Fixes

* **ui:** :bug: split manual upload into choose-file and upload steps ([f6e691f](https://github.com/stkr22/inky-image-display/commit/f6e691f1631fa7315a9df59a0cb532bf2b9e2dac))
* **ui:** :bug: split manual upload into choose-file and upload steps ([c0e93bf](https://github.com/stkr22/inky-image-display/commit/c0e93bfcc6e5239b81dbefddde405e8b3953be16))

## [1.2.3](https://github.com/stkr22/inky-image-display/compare/v1.2.2...v1.2.3) (2026-04-22)


### Bug Fixes

* **api,sync,ui:** :bug: swap device dims for portrait image matching ([cb4f219](https://github.com/stkr22/inky-image-display/commit/cb4f219a4a5853821e1c95626d423c5d84fcf745))
* **api,sync,ui:** :bug: swap device dims for portrait image matching ([d35a4f1](https://github.com/stkr22/inky-image-display/commit/d35a4f1074680f8eb3051fe147b592b180879b2c))

## [1.2.2](https://github.com/stkr22/inky-image-display/compare/v1.2.1...v1.2.2) (2026-04-22)


### Bug Fixes

* **api,sync,ui:** :bug: align image orientation on device-natural dims ([f97dd06](https://github.com/stkr22/inky-image-display/commit/f97dd06b4e38353ca7b132ab410e7fe9eb164792))
* **api,sync,ui:** :bug: align image orientation on device-natural dims ([6cc1cbf](https://github.com/stkr22/inky-image-display/commit/6cc1cbf80024e315c78b444d6a0fb53a84f7e56d))

## [1.2.1](https://github.com/stkr22/inky-image-display/compare/v1.2.0...v1.2.1) (2026-04-22)


### Bug Fixes

* **ui:** :bug: register FilePicker as service instead of overlay ([37784ee](https://github.com/stkr22/inky-image-display/commit/37784ee5f86ae305aae3d9a12db5f856039dcfcd))
* **ui:** :bug: register FilePicker as service instead of overlay ([c5a051c](https://github.com/stkr22/inky-image-display/commit/c5a051cdf2c7fc6e975c8a5150fd0f0b81d12a59))

## [1.2.0](https://github.com/stkr22/inky-image-display/compare/v1.1.0...v1.2.0) (2026-04-21)


### Features

* **sync:** :sparkles: track source_id and sync_job_name on images ([dff583b](https://github.com/stkr22/inky-image-display/commit/dff583b3195593bf38a5d3a0797b2437a8410524))


### Bug Fixes

* **sync:** :bug: apply EXIF orientation before resize/crop ([cffd6a6](https://github.com/stkr22/inky-image-display/commit/cffd6a62cc4024069ba875f932dfd05468af78d7))

## [1.1.0](https://github.com/stkr22/inky-image-display/compare/v1.0.2...v1.1.0) (2026-04-20)


### Features

* **ui:** :sparkles: add Flet web UI for image/device/sync-job management ([0937e30](https://github.com/stkr22/inky-image-display/commit/0937e30e4534bc1ca6eae97c49da083ab047bd82))

## [1.0.2](https://github.com/stkr22/inky-image-display/compare/v1.0.1...v1.0.2) (2026-04-18)


### Bug Fixes

* :bug: pin inky-image-display-shared&gt;=0.3.0 in controller ([b852249](https://github.com/stkr22/inky-image-display/commit/b85224984b228fc4d2f5050ac48be783a998a471))
* :bug: pin inky-image-display-shared&gt;=0.3.0 in controller ([e6fdabe](https://github.com/stkr22/inky-image-display/commit/e6fdabe267f22b52a8d5445bf54e2a63e5f9176f))

## [1.0.1](https://github.com/stkr22/inky-image-display/compare/v1.0.0...v1.0.1) (2026-04-18)


### Bug Fixes

* :bug: use slim-trixie runtime to match build stage libc ([e07dbda](https://github.com/stkr22/inky-image-display/commit/e07dbda34ef5d75763e07b62753b972e422db464))
* :bug: use slim-trixie runtime to match build stage libc ([548079b](https://github.com/stkr22/inky-image-display/commit/548079b3a8f9e40f4cfe2f26ce0160f91c0f6fc0))

## [1.0.0](https://github.com/stkr22/inky-image-display/compare/v0.6.0...v1.0.0) (2026-04-18)


### ⚠ BREAKING CHANGES

* drop support for python 3.12 and add python 3.14 support

### Features

* drop support for python 3.12 and add python 3.14 support ([e25fef7](https://github.com/stkr22/inky-image-display/commit/e25fef734d435a45734189ad0192840c658c62fd))
* drop support for python 3.12 and add python 3.14 support ([fbc18e0](https://github.com/stkr22/inky-image-display/commit/fbc18e090c8f19a125aad99c034407a9c4281f3b))


### Bug Fixes

* :bug: resolve websocket test hang with NullPool and temp-file SQLite ([38b2f60](https://github.com/stkr22/inky-image-display/commit/38b2f607efc320c3ad74a5c5b49cd139ec5b8d8d))
* merging config into pyproject.toml and adding timout for tests; ([13e3547](https://github.com/stkr22/inky-image-display/commit/13e35478eeb002702b43299f1cc6714325e34db8))

## [0.6.0](https://github.com/stkr22/inky-image-display/compare/v0.5.1...v0.6.0) (2026-04-18)


### Features

* :sparkles: add shared rich logging and fix sync service silent failures ([7b77ff3](https://github.com/stkr22/inky-image-display/commit/7b77ff30a7e97cc6fde52a7478e9b8e07e924735))

## [0.5.1](https://github.com/stkr22/inky-image-display/compare/v0.5.0...v0.5.1) (2026-04-17)


### Bug Fixes

* :bug: add websockets support via uvicorn[standard] ([4b90b02](https://github.com/stkr22/inky-image-display/commit/4b90b02398aa111ccc15ceba4d98ae07141b9900))
* :bug: add websockets support via uvicorn[standard] ([5b80fac](https://github.com/stkr22/inky-image-display/commit/5b80fac5db32fbcde9221d10a6c332fbf3675fd8))

## [0.5.0](https://github.com/stkr22/inky-image-display/compare/v0.4.0...v0.5.0) (2026-04-17)


### Features

* :sparkles: publish inky-image-display-shared to PyPI ([bb97fab](https://github.com/stkr22/inky-image-display/commit/bb97fab28a4ae5458bc6a4f58f88823dfbb44dd6))
* :sparkles: publish inky-image-display-shared to PyPI ([1eaa8e8](https://github.com/stkr22/inky-image-display/commit/1eaa8e86a3d02a827c43693f1daeae3138cd6ed0))

## [0.4.0](https://github.com/stkr22/inky-image-display/compare/v0.3.1...v0.4.0) (2026-04-16)


### Features

* :sparkles: add GET /health endpoint to api service ([1c05a87](https://github.com/stkr22/inky-image-display/commit/1c05a8711fbc8e94071f4692a3419190155baa27))
* :sparkles: add GET /health endpoint to api service ([479afb3](https://github.com/stkr22/inky-image-display/commit/479afb3a999f94753a19522ff7aeab35f71f59d9))

## [0.3.1](https://github.com/stkr22/inky-image-display/compare/v0.3.0...v0.3.1) (2026-04-16)


### Bug Fixes

* :bug: add missing Pillow dependency to api package ([a83e08f](https://github.com/stkr22/inky-image-display/commit/a83e08fec3a2076bc9cc713d3be1614dcf18a06d))
* remove unused controller service from container build workflows ([ff8e9c2](https://github.com/stkr22/inky-image-display/commit/ff8e9c2afae4e18627415ff55710ad702df604b8))


### Documentation

* :memo: update sync config docs and fix container workflow trigger ([5e661c8](https://github.com/stkr22/inky-image-display/commit/5e661c84e5ac04f99cebdaecfbce9e87695cc9bc))

## [0.3.0](https://github.com/stkr22/inky-image-display/compare/v0.2.0...v0.3.0) (2026-04-16)


### Features

* :recycle: remove direct SQLite access from sync service ([826bd49](https://github.com/stkr22/inky-image-display/commit/826bd49fcce8b4aef4076f94335abaf552a480da)), closes [#7](https://github.com/stkr22/inky-image-display/issues/7)


### Bug Fixes

* :wrench: configure release-please for controller PyPI releases ([6dddc4c](https://github.com/stkr22/inky-image-display/commit/6dddc4ca9a22f35005195ae27c13a5c84cdd7114))
* :wrench: update postCreateCommand to sync all packages in dev environment ([bd553c3](https://github.com/stkr22/inky-image-display/commit/bd553c313091de61721de4dc5525909eae04715b))


### Documentation

* :memo: update configuration and deployment docs for SQLite migration ([c6c6053](https://github.com/stkr22/inky-image-display/commit/c6c6053244b54fd3b844e00bacd32839846b60ad))

## [0.2.0](https://github.com/stkr22/inky-image-display/compare/v0.1.1...v0.2.0) (2026-04-16)


### Features

* :recycle: migrate database from PostgreSQL to SQLite ([ea1969b](https://github.com/stkr22/inky-image-display/commit/ea1969b0acf6f61e5b0acf99b35627c0eea91e84))
* :recycle: migrate database from PostgreSQL to SQLite ([affdd4a](https://github.com/stkr22/inky-image-display/commit/affdd4a4493e157df654f5fe163341357fb4b223))

## [0.1.1](https://github.com/stkr22/inky-image-display/compare/v0.1.0...v0.1.1) (2026-04-15)


### Bug Fixes

* :bug: scope PyPI release workflow to controller package only ([51cf663](https://github.com/stkr22/inky-image-display/commit/51cf66381d2648271e39028c90eaefe3581c4052))
* :bug: scope PyPI release workflow to controller package only ([87e2ba0](https://github.com/stkr22/inky-image-display/commit/87e2ba0905fc019320647766c793696cd9ea2d5f))

## 0.1.0 (2026-04-15)


### Features

* :sparkles: add FastAPI management service ([e060925](https://github.com/stkr22/inky-image-display/commit/e060925602d6e6a0d2330ff85dd81a53a416e695))
* :sparkles: add Immich image sync service ([b6f90a8](https://github.com/stkr22/inky-image-display/commit/b6f90a81575838cf410d3ada7b970902176c5e53))
* :sparkles: add Inky display controller for Raspberry Pi ([bdb2752](https://github.com/stkr22/inky-image-display/commit/bdb27522529897129a36733b47960f0faea93198))
* :sparkles: add shared SQLModel models and Pydantic schemas ([5351760](https://github.com/stkr22/inky-image-display/commit/53517604edc3d627b3c2e46bc842215f26f6a277))


### Documentation

* :memo: rewrite README and docs to reflect current architecture ([51e26a7](https://github.com/stkr22/inky-image-display/commit/51e26a7f46757cff03e7b67eda1b3661d4e43836))
