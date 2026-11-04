"""Extract the prototype stylesheet and scope it under `.ifc`.

Source: 02-docs/02-course/02-doc/02-design/prototype-v5-inflow-library.html
Output: app/courses/prototype.css

The prototype is a standalone page, so it also styles the app shell
(sidebar / mobile bar / body). Those rules are dropped here — the Next.js
app already owns the shell. Everything else is prefixed with `.ifc` so the
prototype component classes (.panel / .btn / .badge / .card ...) cannot leak
into other pages.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]  # inFlow-AI
PROTO = ROOT / "02-docs/02-course/02-doc/02-design/prototype-v5-inflow-library.html"
OUT = ROOT / "03-src/frontend/app/courses/prototype.css"

html = PROTO.read_text(encoding="utf-8")
css = re.search(r"<style>\n(.*?)\n</style>", html, re.S).group(1)

# Strip comments (keep the sheet compact; section banners are re-added below).
css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

DROP_PRELUDE = {
    "*",
    "html",
    "body",
    "button, input, textarea",
    "button",
    "a",
}

KEYFRAME_RENAME = {
    "fadeIn": "ifcFadeIn",
    "slideIn": "ifcSlideIn",
    "popIn": "ifcPopIn",
    "pulse": "ifcPulse",
}


def split_selectors(prelude: str):
    return [s.strip() for s in prelude.split(",") if s.strip()]


SHELL_EXACT = {
    ".app",
    ".sidebar",
    ".main",
    ".page",
    ".mobile-bar",
    ".sidebar-overlay",
    ".logo-row",
    ".logo-mark",
    ".logo-name",
    ".sidebar-foot",
    ".foot-btn",
}


def is_shell_selector(sel: str) -> bool:
    first = sel.split()[0]
    return (
        first in SHELL_EXACT
        or first.startswith(".sidebar.")
        or first.startswith(".sidebar-overlay")
        or first.startswith(".nav")
        or first.startswith(".logo-")
        or first.startswith(".foot-btn")
        or first.startswith(".page.")
    )


def scope_selector(sel: str) -> str:
    if sel == '[data-theme="dark"]':
        return ".dark .ifc"
    if sel.startswith('[data-theme="dark"]'):
        return ".dark .ifc " + sel[len('[data-theme="dark"]'):].strip()
    return f".ifc {sel}"


def process(block: str, top_level: bool) -> str:
    out = []
    i = 0
    n = len(block)
    buf = []

    def flush():
        nonlocal buf
        if buf:
            out.append("".join(buf))
            buf = []

    while i < n:
        ch = block[i]
        if ch == "{":
            prelude = "".join(buf).strip()
            buf = []
            # find matching close brace
            depth = 1
            j = i + 1
            while j < n and depth:
                if block[j] == "{":
                    depth += 1
                elif block[j] == "}":
                    depth -= 1
                j += 1
            inner = block[i + 1 : j - 1]
            i = j

            if prelude.startswith("@media") or prelude.startswith("@supports"):
                out.append(f"{prelude}{{\n{process(inner, False)}}}\n")
            elif prelude.startswith("@keyframes"):
                name = prelude.split()[1]
                new_name = KEYFRAME_RENAME.get(name, f"ifc{name[0].upper()}{name[1:]}")
                body = re.sub(
                    r"\b(" + "|".join(KEYFRAME_RENAME) + r")\b",
                    lambda m: KEYFRAME_RENAME[m.group(1)],
                    inner,
                )
                out.append(f"@keyframes {new_name}{{{body}}}\n")
            elif prelude.startswith("@"):
                out.append(f"{prelude}{{{inner}}}\n")
            else:
                sels = split_selectors(prelude)
                if top_level and all(s in DROP_PRELUDE for s in sels):
                    continue
                sels = [s for s in sels if not is_shell_selector(s)]
                if not sels:
                    continue
                if sels == [":root"]:
                    out.append(f".ifc{{{inner}}}\n")
                    continue
                scoped = ", ".join(scope_selector(s) for s in sels)
                out.append(f"{scoped}{{{inner}}}\n")
        elif ch == "}":
            # stray close brace at top level — ignore
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    flush()
    return "".join(out)


result = process(css, True)

# Rename animation references too (keyframes were renamed above).
for old, new in KEYFRAME_RENAME.items():
    result = re.sub(rf"(?<![\w-]){old}(?![\w-])", new, result)

header = """/* ==========================================================================
   inFlow AI · 课程模块样式
   由 prototype-v5-inflow-library.html 提取，全部规则作用域在 .ifc 之下。
   重新生成：python scripts/build-course-css.py
   ========================================================================== */

.ifc {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

"""

result = header + result
# collapse excessive blank lines
result = re.sub(r"\n{3,}", "\n\n", result)
OUT.write_text(result, encoding="utf-8")
print(f"wrote {OUT} ({len(result)} bytes)")
