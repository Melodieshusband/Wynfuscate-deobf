# Created by: Melodie's husband (Meloten)
<div align="center">

# Wynfuscate Deobfuscator

Deobfuscation toolkit for scripts protected by wYnFuscate: static string extraction, dynamic execution logging, and an experimental hybrid engine.

![Python](https://img.shields.io/badge/python-3-3776AB?logo=python&logoColor=white)
![Luau](https://img.shields.io/badge/luau-bundled-00A2FF)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)
![Status](https://img.shields.io/badge/status-WIP-orange)

</div>

> **To the author's knowledge, this is the first open-source deobfuscator for wYnFuscate.**

## Status

| Tool | Path | State |
|------|------|-------|
| Dynamic | `dynamic/wynfuscate_deob.py` | Usable, works on obfuscated scripts |
| Static | `static/wynfuscate_static.py` | Usable, works on obfuscated scripts |
| Hybrid | `hybrid/hybrid.py` | **Not ready for use, very raw** |

> **The hybrid engine is not ready for use.** It is very raw, built around a single analyzed sample, with many parameters still hardcoded, so expect it to break on anything else. Do not rely on it. For real scripts use the **dynamic** and **static** tools, which can already work with wYnFuscate-obfuscated scripts more or less reliably. All three are still work in progress, so results can be incomplete and the API and layout may change.

## Features

- **Dynamic**: runs the protected script in bundled Luau with a hooked environment and rewrites the recorded activity (calls, `Instance.new`, `HttpGet`, `loadstring`, etc.) back into plain Lua
- **Static**: decodes the string pool without running the script, brute-forces the pool key, resolves hashed global names and writes a string dump plus a report
- **Hybrid** (experimental): decodes protos and traps statically, rewrites the real opcode handlers and executes them on Luau against a recorder proxy
- Bundled Luau and key brute-forcer binaries, no compiler needed

## Installation

```bash
git clone https://github.com/Melodieshusband/Wynfuscate-deobf.git
cd Wynfuscate-deobf
```

Only Python 3 is required. Luau (`bin/luau`, `bin/luau.exe`) and the key brute-forcer (`bin/bf`, `bin/bf.exe`) are included.

On Linux, make the binaries executable once:

```bash
chmod +x bin/luau bin/bf
```

## Usage

### Dynamic (recommended)

```bash
python3 dynamic/wynfuscate_deob.py samples/input.lua
python3 dynamic/wynfuscate_deob.py samples/input.lua -o out.lua --timeout 120
```

| Option | Description |
|--------|-------------|
| `input` | obfuscated script |
| `-o, --output` | output file, default `<input>_deobfuscated.lua` |
| `--luau PATH` | custom Luau binary, default is the bundled one |
| `--timeout N` | execution timeout in seconds, default 60 |
| `--keep-runner` | keep the generated runner script |
| `--keep-probes` | keep probe statements in the output |
| `--dump-strings FILE` | also dump the decoded strings to a file |

### Static

```bash
python3 static/wynfuscate_static.py samples/input.lua -o report/
python3 static/wynfuscate_static.py samples/input.lua --qe 1849543054
```

| Option | Description |
|--------|-------------|
| `input` | obfuscated script |
| `-o, --out-dir` | output directory, default is next to the input |
| `--qe N` | skip the key search and use this pool key |
| `--all` | include protector strings and binary blobs in the report |

Writes `<name>_strings.txt` and `<name>_static_report.txt`. The key search takes about a minute.

### Hybrid (experimental, not ready)

```bash
python3 hybrid/hybrid.py > out.lua
python3 hybrid/hybrid.py /path/to/luau > out.lua
```

The input is fixed to `samples/input.lua` and the analysis parameters are hardcoded. Use it only for research.

## Example

Recovered output for the bundled sample:

```lua
warn("Imran")
task.wait(5)
print("Meloten")
```

More outputs in `examples/`: `dynamic_output.lua`, `static_output.lua`, `hybrid_output.lua`.

## How it works

**Dynamic**

```
obfuscated.lua
   │
   ▼
runner built around the script + hook (dynamic/hook/deob_hook.lua)
   │
   ▼
executed by bundled Luau, calls recorded through proxies
   │
   ▼
log cleanup (prune, inline constructors, merge loaders, inline HTTP, strip probes)
   │
   ▼
plain Lua
```

**Static**

```
obfuscated.lua
   │
   ▼
parse records and data buffer
   │
   ▼
pool key search (bin/bf)
   │
   ▼
string pool decoded and classified, hashed names resolved
   │
   ▼
strings + report
```

**Hybrid**

```
obfuscated.lua
   │
   ▼
static decoding (strings, protos, fields, traps, hashes)
   │
   ▼
opcode handlers rewritten
   │
   ▼
executed by Luau against a recorder proxy
   │
   ▼
recorded calls → plain Lua
```

## Project layout

```
bin/
    luau, luau.exe              bundled Luau interpreter
    bf, bf.exe                  key brute-forcer
dynamic/
    wynfuscate_deob.py          dynamic deobfuscator
    hook/deob_hook.lua          Luau hook environment and recorder
static/
    wynfuscate_static.py        static string pool extractor
hybrid/
    hybrid.py                   hybrid entry point (experimental)
engine/
    wyn_static.py               static decoder and key search
    wyn_opcodes.py              opcode handler extraction
    decompile.py                recorded calls to Lua source
    minilua.py                  minimal Lua interpreter
    symrun.py, symvm.py         symbolic execution helpers
    run_cx.py, run_or.py        runner helpers
    search_traps.py             trap outcome search
    harness.py, luastr.py       shared helpers
    proto_stream/               stream analysis and brute-force tools (C and Python)
    traps.json, l3.json         analysis data
    stream_lm.txt               analysis data
    stream_cipher.bin           analysis data
samples/
    input.lua                   sample obfuscated script
examples/
    dynamic_output.lua          dynamic tool output
    static_output.lua           static tool output
    hybrid_output.lua           hybrid tool output
```

## Limitations

- **Hybrid is not ready for use**: very raw, single-sample, hardcoded parameters, branches always take the first path, no loops or functions yet
- Dynamic and static work on obfuscated scripts, but coverage is not complete and output may be partial on unusual variants
- Dynamic output depends on what the script actually executes before the timeout
- No tests and little error handling, API and layout will change

## Disclaimer

This tool is intended for analyzing your own scripts and for obfuscation research. Respect the licenses and rights of other authors' code.

## License

Licensed under the [Apache License 2.0](LICENSE). Bundled Luau is MIT licensed, see [luau-lang/luau](https://github.com/luau-lang/luau).
