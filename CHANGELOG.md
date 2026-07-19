# Changelog

## [5.12.0](https://github.com/stkr22/inky-image-display/compare/v5.11.0...v5.12.0) (2026-07-19)


### Features

* restructure MOTD into grid-targeting display jobs ([d634095](https://github.com/stkr22/inky-image-display/commit/d6340950c52fa7687cea6dfa4776e8828b7ca7f9))
* restructure MOTD into grid-targeting display jobs ([1497c94](https://github.com/stkr22/inky-image-display/commit/1497c94ddef675ef7304eac941bfec0618eb98a0))

## [5.11.0](https://github.com/stkr22/inky-image-display/compare/v5.10.0...v5.11.0) (2026-07-18)


### Features

* **sync:** selectable AND/OR matching for album and person filters ([ef82f50](https://github.com/stkr22/inky-image-display/commit/ef82f50b2b315360e8de2573e1de209ae77517cc))
* **sync:** selectable AND/OR matching for album and person filters ([0c4499a](https://github.com/stkr22/inky-image-display/commit/0c4499ad68fb8ff5c106130851bec3835cd77c52))
* **web:** surface Immich lookup failures and explain sync-job options ([ba200f1](https://github.com/stkr22/inky-image-display/commit/ba200f1c8733e54cef6caf28e419b77c440085ff))


### Bug Fixes

* **api:** stagger rotation rejoin after MOTD release ([49d3055](https://github.com/stkr22/inky-image-display/commit/49d305588beee5114b85f226c08cdd6c59478efd))

## [5.10.0](https://github.com/stkr22/inky-image-display/compare/v5.9.3...v5.10.0) (2026-07-11)


### Features

* **api:** curation, quiet hours, refresh-health states, run tracking, e-ink preview ([3d14cbf](https://github.com/stkr22/inky-image-display/commit/3d14cbf315974813cb362d5c0cba6a51e1b5bebf))
* **sync:** report run outcomes and support UI-triggered runs ([3b57dbf](https://github.com/stkr22/inky-image-display/commit/3b57dbfd0d3206f1b1f799af068401b2e813b86e))
* **web:** surface fleet health, curation, run history and e-ink previews ([767a093](https://github.com/stkr22/inky-image-display/commit/767a093333e33eb25ab74dab7e8143f0ad3b0695))


### Documentation

* cover quiet hours, run reporting, health states and e-ink previews ([f84c880](https://github.com/stkr22/inky-image-display/commit/f84c880c4dfa8cb54ce8c47160349adc578a0834))

## [5.9.3](https://github.com/stkr22/inky-image-display/compare/v5.9.2...v5.9.3) (2026-07-11)


### Bug Fixes

* stop failed-refresh halt from outliving the controller retry ([33a537d](https://github.com/stkr22/inky-image-display/commit/33a537d26112658a7f15f3ee8302cc09a81d78ac))

## [5.9.2](https://github.com/stkr22/inky-image-display/compare/v5.9.1...v5.9.2) (2026-07-10)


### Bug Fixes

* **controller:** stop powering off EL133UF1 mid-refresh ([82a0b65](https://github.com/stkr22/inky-image-display/commit/82a0b65790cf4ebbf2a780e6ef1376dba2c211f1))
* **controller:** stop powering off EL133UF1 mid-refresh ([ff0ab74](https://github.com/stkr22/inky-image-display/commit/ff0ab74c475f14485adb05511dff5d3255d62d37))
* **controller:** type patched driver class as Any for ty ([d6b2283](https://github.com/stkr22/inky-image-display/commit/d6b2283824ff8d9e361623ffdb607003fce9d060))

## [5.9.1](https://github.com/stkr22/inky-image-display/compare/v5.9.0...v5.9.1) (2026-07-05)


### Bug Fixes

* **auth:** machine token settings ignored documented env var names ([379a3ac](https://github.com/stkr22/inky-image-display/commit/379a3ac1a99445b5ef01685b9dcd57344cd016fa))
* **auth:** machine token settings ignored documented env var names ([828f577](https://github.com/stkr22/inky-image-display/commit/828f5778dbf1b72d885268a47af479bcf45585bd))

## [5.9.0](https://github.com/stkr22/inky-image-display/compare/v5.8.1...v5.9.0) (2026-07-05)


### Features

* **auth:** optional OIDC auth, guest invite links, machine tokens ([d9efe13](https://github.com/stkr22/inky-image-display/commit/d9efe13edf8bd8545e2ee4b76856d22f51a33ecc))
* **auth:** optional OIDC auth, guest invite links, machine tokens ([4086244](https://github.com/stkr22/inky-image-display/commit/4086244b9be7332480d2b1142f3764bf9b367a9d))

## [5.8.1](https://github.com/stkr22/inky-image-display/compare/v5.8.0...v5.8.1) (2026-07-04)


### Bug Fixes

* **motd:** make story parts carry distinct information ([b4e545e](https://github.com/stkr22/inky-image-display/commit/b4e545eaae551992f2a07eca47ed71f7111996dc))
* **motd:** make story parts carry distinct information ([b97c1b2](https://github.com/stkr22/inky-image-display/commit/b97c1b2c3f2b1db71116cbad748da8a9489d110a))

## [5.8.0](https://github.com/stkr22/inky-image-display/compare/v5.7.0...v5.8.0) (2026-07-03)


### Features

* **motd:** render screens on demand, add 7-day story history with redisplay ([de79277](https://github.com/stkr22/inky-image-display/commit/de79277d35ce632150637e5b74b457b6160b6567))
* **motd:** render screens on demand, add 7-day story history with redisplay ([b933127](https://github.com/stkr22/inky-image-display/commit/b93312712a3fdb7d3ff64cb6f9ed720312b7c8b4))

## [5.7.0](https://github.com/stkr22/inky-image-display/compare/v5.6.0...v5.7.0) (2026-07-03)


### Features

* add Helm chart published to GHCR on release ([e2548dc](https://github.com/stkr22/inky-image-display/commit/e2548dcf7da338883aff29c8c7194fefff76d7f9))

## [5.6.0](https://github.com/stkr22/inky-image-display/compare/v5.5.0...v5.6.0) (2026-07-03)


### Features

* add message-of-the-day story takeover across displays ([6ad2020](https://github.com/stkr22/inky-image-display/commit/6ad20204fec338761d88b4a46e017a0feb216264))


### Bug Fixes

* log grid rotation with pre-commit ids to avoid MissingGreenlet ([e5dcf77](https://github.com/stkr22/inky-image-display/commit/e5dcf7729747c2c8611b21b28966266a8b73e72f))

## [5.5.0](https://github.com/stkr22/inky-image-display/compare/v5.4.2...v5.5.0) (2026-06-28)


### Features

* make Immich image cap per-job instead of global ([f0b5d6c](https://github.com/stkr22/inky-image-display/commit/f0b5d6c865566799a1091d44019ce7aa127cf2ae))
* make Immich image cap per-job instead of global ([82b720e](https://github.com/stkr22/inky-image-display/commit/82b720e1620eb7ca4a27c78b6aa02843c4affe0f))

## [5.4.2](https://github.com/stkr22/inky-image-display/compare/v5.4.1...v5.4.2) (2026-06-23)


### Bug Fixes

* round up cover-fit dimensions to prevent 1px display mismatch ([c810b53](https://github.com/stkr22/inky-image-display/commit/c810b530191f7a06928ba53a66774e96d40e7a1b))
* round up cover-fit dimensions to prevent 1px display mismatch ([c0bc0ba](https://github.com/stkr22/inky-image-display/commit/c0bc0ba0ea33e78501615f0804417bb5391c9ee0))

## [5.4.1](https://github.com/stkr22/inky-image-display/compare/v5.4.0...v5.4.1) (2026-06-14)


### Bug Fixes

* correct BUSY-pin polarity so healthy 13.3 refreshes aren't flagged as stalled ([ad9c3f8](https://github.com/stkr22/inky-image-display/commit/ad9c3f8ea581fcb5224a7954ce6c014ed139ad57))
* correct BUSY-pin polarity so healthy 13.3 refreshes aren't flagged as stalled ([fff8b68](https://github.com/stkr22/inky-image-display/commit/fff8b686f60ffa4cfcdf6afb7076df9316f80eb7))
* **web:** stack device card image and status on narrow screens ([7f6d795](https://github.com/stkr22/inky-image-display/commit/7f6d795a778eda3d992d437e2c9d3afc4c4d2be1))
* **web:** stack device card image and status on narrow screens ([5c461f5](https://github.com/stkr22/inky-image-display/commit/5c461f59d3bc11543e07473536374f8c7a2cb483))

## [5.4.0](https://github.com/stkr22/inky-image-display/compare/v5.3.0...v5.4.0) (2026-06-14)


### Features

* stop auto-dispatching images to devices with a failed refresh ([c08c683](https://github.com/stkr22/inky-image-display/commit/c08c68363d038d1d315de853757f59138ca4a512))
* stop auto-dispatching images to devices with a failed refresh ([fc9745e](https://github.com/stkr22/inky-image-display/commit/fc9745e625aa9b4221743c456f5a6f9e2890eae8))

## [5.3.0](https://github.com/stkr22/inky-image-display/compare/v5.2.0...v5.3.0) (2026-06-13)


### Features

* detect silent 13.3 refresh stalls via BUSY-pin watching ([711bb2d](https://github.com/stkr22/inky-image-display/commit/711bb2dbee61f7b971b3cfea6f232982afa263b6))
* detect silent 13.3 refresh stalls via BUSY-pin watching ([d80c4cb](https://github.com/stkr22/inky-image-display/commit/d80c4cbd722cc9abd29e99a5b0ed774c32cb872c))

## [5.2.0](https://github.com/stkr22/inky-image-display/compare/v5.1.0...v5.2.0) (2026-06-13)


### Features

* richer painterly defaults for Spectra 6 generation ([6302e3a](https://github.com/stkr22/inky-image-display/commit/6302e3a4dcc66c0adfd7e205e39928ccda94aa3f))


### Bug Fixes

* keep benign Inky ResourceWarning out of the refresh log ([22732ab](https://github.com/stkr22/inky-image-display/commit/22732ab267fcdfb5260f92e0ff2444c8f6412330))

## [5.1.0](https://github.com/stkr22/inky-image-display/compare/v5.0.0...v5.1.0) (2026-06-13)


### Features

* detect stalled display refreshes and surface them in the UI ([3b41021](https://github.com/stkr22/inky-image-display/commit/3b4102172ada7bd72e8b759d7313572af61711d9))


### Bug Fixes

* make bare `alembic upgrade head` work on an empty database ([653c1eb](https://github.com/stkr22/inky-image-display/commit/653c1eb40263669a9ae40eab23d64d6c338a5961))


### Documentation

* update README architecture for the React frontend ([1db7093](https://github.com/stkr22/inky-image-display/commit/1db7093d047efec9030db88ad4a153422cab3710))
* update README architecture for the React frontend ([7c012f6](https://github.com/stkr22/inky-image-display/commit/7c012f63a32a1fe181096e8b7eaec0c232da3ef0))

## [5.0.0](https://github.com/stkr22/inky-image-display/compare/v4.7.0...v5.0.0) (2026-06-12)


### ⚠ BREAKING CHANGES

* replace NiceGUI UI with React frontend served by the API

### Features

* replace NiceGUI UI with React frontend served by the API ([701586a](https://github.com/stkr22/inky-image-display/commit/701586a95621eb09445ddae757f00d69ad0b3ad5))

## [4.7.0](https://github.com/stkr22/inky-image-display/compare/v4.6.0...v4.7.0) (2026-06-01)


### Features

* **sync:** support ANY-tag union for RANDOM Immich jobs ([d95f7fa](https://github.com/stkr22/inky-image-display/commit/d95f7fa3081f4167d8e3512fa57e568449f0002e))
* **sync:** support ANY-tag union for RANDOM Immich jobs ([537647e](https://github.com/stkr22/inky-image-display/commit/537647eec6808fac178e1116e452ca62adf6bd64))


### Documentation

* clarify project scope and surface UI/grids in README ([1aba994](https://github.com/stkr22/inky-image-display/commit/1aba994348410b7f4b19d129ec903f362beea079))

## [4.6.0](https://github.com/stkr22/inky-image-display/compare/v4.5.0...v4.6.0) (2026-05-20)


### Features

* **ui:** collapse Devices/Grids/Schedule into Displays and add image-driven send ([012fd7d](https://github.com/stkr22/inky-image-display/commit/012fd7dba042b26e7cf4edd2e422d1cb0f8faf1f))
* **ui:** collapse Devices/Grids/Schedule into Displays and add image… ([2f722f7](https://github.com/stkr22/inky-image-display/commit/2f722f77c8db96aefe3254a946819f6cd427d0e6))

## [4.5.0](https://github.com/stkr22/inky-image-display/compare/v4.4.0...v4.5.0) (2026-05-19)


### Features

* **ui:** chip inputs for ID lists and editable global default refresh ([06738ba](https://github.com/stkr22/inky-image-display/commit/06738ba802dbd87c34aa16de109a1b6cb393b220))
* **ui:** chip inputs for ID lists and editable global default refresh ([c8da96b](https://github.com/stkr22/inky-image-display/commit/c8da96b07740ba82efa44c709c5680243e28243c))

## [4.4.0](https://github.com/stkr22/inky-image-display/compare/v4.3.0...v4.4.0) (2026-05-17)


### Features

* **scripts:** add Immich album/person suitability analyser ([feda0ad](https://github.com/stkr22/inky-image-display/commit/feda0ad36b85f43ce95961e604ffc822a2e39f50))


### Bug Fixes

* move resize to API endpoint; drop sync quality filters ([c3137f1](https://github.com/stkr22/inky-image-display/commit/c3137f19e0d8b70096379c17a4086c0ae0dc1ac0))

## [4.3.0](https://github.com/stkr22/inky-image-display/compare/v4.2.1...v4.3.0) (2026-05-17)


### Features

* user-editable refresh schedules and local-time rendering ([1fcfb9c](https://github.com/stkr22/inky-image-display/commit/1fcfb9c6d3bc53dc58065f6af1d522ff2cdd1a22))


### Bug Fixes

* **api:** skip empty grids in the rotation background tick ([a0b7885](https://github.com/stkr22/inky-image-display/commit/a0b7885e9bad6623925ff77dd00c129f322e383b))

## [4.2.1](https://github.com/stkr22/inky-image-display/compare/v4.2.0...v4.2.1) (2026-05-16)


### Bug Fixes

* **api:** refresh grid after release to avoid async lazy-load on delete ([aa3a91e](https://github.com/stkr22/inky-image-display/commit/aa3a91e225de39e4e9d4fef2781f64991539f805))

## [4.2.0](https://github.com/stkr22/inky-image-display/compare/v4.1.0...v4.2.0) (2026-05-16)


### Features

* **grids:** anchor device placement at bottom-left with clearer labels ([d946613](https://github.com/stkr22/inky-image-display/commit/d9466137f51efd7223bfd895efc0077b89c2204a))
* **grids:** anchor device placement at bottom-left with clearer labels ([d909c72](https://github.com/stkr22/inky-image-display/commit/d909c7238d58c2694107d8f480119c1ef0d77fd2))

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
