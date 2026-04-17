# Changelog

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
