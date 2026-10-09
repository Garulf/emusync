# Changelog

## [0.2.0](https://github.com/Garulf/emusync/compare/emusync-v0.1.0...emusync-v0.2.0) (2026-10-09)


### Features

* add emusync command line ([f79d0a5](https://github.com/Garulf/emusync/commit/f79d0a5f4e4c9d9e54164aa88fc381872d79619e))
* add manifest model and folder scanning ([5eee47d](https://github.com/Garulf/emusync/commit/5eee47d62c550b8e4ed3a6998e184c1c7821bba5))
* add sync decision function ([b4ba1e0](https://github.com/Garulf/emusync/commit/b4ba1e03e4c4f01999e993482374306e9edc99f3))
* **client:** add config, slot discovery and sync state ([ff0e138](https://github.com/Garulf/emusync/commit/ff0e1380b8dbb18b5cbdff81b4a0ede0f46d0e88))
* **client:** add conflict prompts for terminal and Game Mode ([3df06eb](https://github.com/Garulf/emusync/commit/3df06ebbbcf88ab460585cf844bca9bde14fc02b))
* **client:** add sync engine with push, pull and safety guards ([7f96f93](https://github.com/Garulf/emusync/commit/7f96f93f04fd61b5e71379d626d1f83dbe43ebe7))
* **client:** add typed API wrapper ([a8708db](https://github.com/Garulf/emusync/commit/a8708dbdabfed51321b0b51f6f323a9da614b5e9))
* **client:** hook sync into EmuDeck launchers ([b3cb9bb](https://github.com/Garulf/emusync/commit/b3cb9bbb0ced74c3df81fd8d6ac55f5dc3c1fd1a))
* **server:** add HTTP API ([938dc9b](https://github.com/Garulf/emusync/commit/938dc9b27dffc1e6e9c25374b877878818feb41b))
* **server:** add versioned save store with retention ([d45c1ce](https://github.com/Garulf/emusync/commit/d45c1cecf4fe225298fb95066fda50e80db0355b))


### Bug Fixes

* ask instead of overwriting when server history diverges ([68a9818](https://github.com/Garulf/emusync/commit/68a98186a896f651d66962e83e8edb000b1ee486))
* **client:** allow restoring a slot whose folder was emptied ([63f82ea](https://github.com/Garulf/emusync/commit/63f82ea87bffa2679b3b5bd88b1d967b217e3e79))
* **client:** default the conflict dialog to Skip and show its text literally ([b4747f7](https://github.com/Garulf/emusync/commit/b4747f780f07f5e6a68b8c273a013e71492e3a78))
* **client:** fsync pulled files and directories before advancing the base ([d3523ab](https://github.com/Garulf/emusync/commit/d3523abb9408336470c67e83d225c75e4ef5997d))
* **client:** never let a bad state file block run or sync ([2036bab](https://github.com/Garulf/emusync/commit/2036bab62d601f184548176bf62876b034d50b98))
* **client:** reject malformed config with ConfigError ([c514fa1](https://github.com/Garulf/emusync/commit/c514fa111d2fd4641fec75a525505707856a3265))
* **client:** replace launchers atomically and resolve emuName ([d498b15](https://github.com/Garulf/emusync/commit/d498b1590f3815ae45cf142f3e2bcfc3f95cb98a))
* **client:** skip xemu and xenia unless enabled in the config ([cc47e58](https://github.com/Garulf/emusync/commit/cc47e58d47c6131cc6794c7f01349488916141ce))
* **client:** treat redirects and malformed responses as server errors ([d984af6](https://github.com/Garulf/emusync/commit/d984af6e542629919002fc2668935bf22bc10679))
* **client:** write an absolute emusync path into launcher hooks ([5ae1f2a](https://github.com/Garulf/emusync/commit/5ae1f2a27f75faebf00f2b119db48a4004f898bb))
* make keep-server conflict resolution atomic ([f062eb1](https://github.com/Garulf/emusync/commit/f062eb1e1216d7f50b496decb8ef6a56d5d1f6dd))
* never block the wrapped command in emusync run ([3ec64ef](https://github.com/Garulf/emusync/commit/3ec64ef5e3b2470db05a823690496e06bfd2cc76))
* **server:** make blob writes durable and post-commit GC best-effort ([408f6c5](https://github.com/Garulf/emusync/commit/408f6c5e603b8193cee2a31e06528deef93a834c))
* **server:** require keeping at least two versions per slot ([979d793](https://github.com/Garulf/emusync/commit/979d79341adb346caf7be1862aaa1baa634f0050))
* **server:** write uploaded blobs in the threadpool ([388ec88](https://github.com/Garulf/emusync/commit/388ec88d4823895d782b63e2422365c28a244bb5))
* use a named volume for server data ([ac25f90](https://github.com/Garulf/emusync/commit/ac25f907ecc05cb5a488bbe0dc996aaf0d3f2740))


### Documentation

* install from the GitHub repository ([391c9f4](https://github.com/Garulf/emusync/commit/391c9f44111358552fb0930d8d4dffec16a551c2))
