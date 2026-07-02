"""
card_toolbar_injector.py

Injects a theme-switcher toolbar (30 themes / font-size / viewport / export)
into any LLM-generated card HTML that uses CSS variables.

Usage
-----
from app.s4_compose.card_toolbar_injector import CardToolbarInjector
injector = CardToolbarInjector()
html_with_toolbar = injector.inject(html_str)

Playwright tip
--------------
After injection, Playwright can:
  await page.evaluate("window.applyTheme(document.body.dataset.theme || 'newspaper')")
Before screenshot:
  await page.evaluate("window.hideToolbar()")
After screenshot (if showing browser):
  await page.evaluate("window.showToolbar()")
"""

import json
import re
from pathlib import Path

# Location of the 30-theme manifest (produced by extract_themes.py)
_THEMES_JSON = (
    Path(__file__).parent.parent.parent
    / "prompts/s4/card_themes_mapped.json"
)


class CardToolbarInjector:
    def __init__(self, themes_path: Path = _THEMES_JSON):
        self._data = json.loads(themes_path.read_text())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inject(self, html: str) -> str:
        """Return html with toolbar injected."""
        head_inject = self._build_head_inject()
        body_inject = self._build_body_inject()

        # Inject before </head>
        html = re.sub(
            r"(</head>)", head_inject + r"\1", html, count=1, flags=re.IGNORECASE
        )
        # Inject right after <body ...>
        html = re.sub(
            r"(<body[^>]*>)", r"\1" + body_inject, html, count=1, flags=re.IGNORECASE
        )
        return html

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _themes_js_constant(self) -> str:
        return "const _CARD_THEMES = " + json.dumps(
            self._data["themes"], ensure_ascii=False
        ) + ";"

    def _categories_js_constant(self) -> str:
        cats = self._data["categories"]
        cat_emoji = {
            "极简": "○", "精致": "✦", "醒目": "◆", "聚焦": "◎",
            "媒体": "⬡", "温暖": "☀", "艺术": "◬", "品牌": "◉",
        }
        items = [{"key": c, "emoji": cat_emoji.get(c, "·")} for c in cats]
        return "const _CARD_CATS = " + json.dumps(items, ensure_ascii=False) + ";"

    def _build_head_inject(self) -> str:
        themes_js = self._themes_js_constant()
        cats_js = self._categories_js_constant()
        toolbar_js = _TOOLBAR_JS_TEMPLATE.replace("__THEMES_PLACEHOLDER__", themes_js).replace(
            "__CATS_PLACEHOLDER__", cats_js
        )
        return f"""
<!-- card-toolbar: html2canvas -->
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<!-- card-toolbar: theme data + logic -->
<style>{_TOOLBAR_CSS}</style>
<script>
{toolbar_js}
</script>
"""

    def _build_body_inject(self) -> str:
        return _TOOLBAR_HTML


# ---------------------------------------------------------------------------
# Toolbar CSS  (scoped to #card-toolbar)
# ---------------------------------------------------------------------------
_TOOLBAR_CSS = """
#card-toolbar {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 99999;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  box-shadow: 0 1px 6px rgba(0,0,0,.08);
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', sans-serif;
  font-size: 12px;
  color: #333;
  user-select: none;
}
#ct-row1 {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px 4px;
  flex-wrap: wrap;
}
#ct-row2 {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px 6px;
  flex-wrap: wrap;
  background: #fafafa;
  border-top: 1px solid #f0f0f0;
}
#ct-brand {
  font-weight: 700;
  font-size: 11px;
  letter-spacing: .03em;
  color: #bfa050;
  margin-right: 4px;
  white-space: nowrap;
}
#ct-cats {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
  flex: 1;
}
.ct-cat-btn {
  padding: 3px 8px;
  border-radius: 12px;
  border: 1px solid #e0e0e0;
  background: #fff;
  cursor: pointer;
  font-size: 11px;
  color: #666;
  transition: all .15s;
  white-space: nowrap;
}
.ct-cat-btn:hover { background: #f5f5f5; }
.ct-cat-btn.ct-active {
  background: #1a1a1a;
  color: #fff;
  border-color: #1a1a1a;
}
.ct-pill {
  padding: 2px 9px;
  border-radius: 10px;
  border: 1px solid #e0e0e0;
  background: #fff;
  cursor: pointer;
  font-size: 11px;
  color: #555;
  transition: all .15s;
  white-space: nowrap;
}
.ct-pill:hover { background: #f0f0f0; }
.ct-pill.ct-active {
  border-color: var(--theme-accent, #4B6EF5);
  color: var(--theme-accent, #4B6EF5);
  background: color-mix(in srgb, var(--theme-accent, #4B6EF5) 8%, #fff);
  font-weight: 600;
}
#ct-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  flex-shrink: 0;
}
#ct-fontsize {
  display: flex;
  gap: 2px;
}
.ct-sz-btn {
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #ddd;
  background: #fff;
  cursor: pointer;
  font-size: 10px;
  color: #555;
  line-height: 1.4;
}
.ct-sz-btn:hover { background: #f5f5f5; }
.ct-sz-btn.ct-active { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
#ct-viewport {
  display: flex;
  gap: 2px;
}
.ct-vp-btn {
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid #ddd;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
}
.ct-vp-btn:hover { background: #f5f5f5; }
.ct-vp-btn.ct-active { background: #1a1a1a; border-color: #1a1a1a; }
#ct-export {
  padding: 3px 10px;
  border-radius: 6px;
  border: none;
  background: linear-gradient(135deg, #bfa050, #d4b87a);
  color: #fff;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .02em;
  white-space: nowrap;
}
#ct-export:hover { opacity: .85; }
/* Body offset so content isn't hidden under fixed toolbar */
body { padding-top: 76px !important; }
/* PC viewport override */
body.vp-pc > *:not(#card-toolbar) { max-width: 1080px; margin-left: auto; margin-right: auto; }
"""

# ---------------------------------------------------------------------------
# Toolbar HTML (minimal shell; JS populates category tabs + pills)
# ---------------------------------------------------------------------------
_TOOLBAR_HTML = """<div id="card-toolbar">
  <div id="ct-row1">
    <span id="ct-brand">THEMES</span>
    <div id="ct-cats"></div>
    <div id="ct-controls">
      <div id="ct-fontsize">
        <button class="ct-sz-btn" data-size="14">A-</button>
        <button class="ct-sz-btn ct-active" data-size="15">A</button>
        <button class="ct-sz-btn" data-size="16">A+</button>
      </div>
      <div id="ct-viewport">
        <button class="ct-vp-btn ct-active" id="ct-mobile" title="移动端 750px">📱</button>
        <button class="ct-vp-btn" id="ct-pc" title="PC 1080px">💻</button>
      </div>
      <button id="ct-export">📷 截图</button>
    </div>
  </div>
  <div id="ct-row2"></div>
</div>
"""

# ---------------------------------------------------------------------------
# Toolbar JS (theme switching / font size / viewport / export)
# Placeholders __THEMES_PLACEHOLDER__ and __CATS_PLACEHOLDER__ are replaced
# by _build_head_inject() with the real JSON data.
# ---------------------------------------------------------------------------
_TOOLBAR_JS_TEMPLATE = """
(function () {
  __THEMES_PLACEHOLDER__
  __CATS_PLACEHOLDER__

  let _currentTheme = (document.body && document.body.dataset.theme) || 'newspaper';
  let _currentCat = null;

  // ---- Core: apply theme vars to :root ----
  function applyTheme(slug) {
    var t = _CARD_THEMES[slug];
    if (!t) return;
    var r = document.documentElement;
    var vars = t.vars;
    for (var k in vars) {
      r.style.setProperty(k, vars[k]);
    }
    _currentTheme = slug;
    document.body.dataset.theme = slug;
    // Update pill active state
    document.querySelectorAll('.ct-pill').forEach(function(p) {
      p.classList.toggle('ct-active', p.dataset.slug === slug);
    });
  }

  // ---- Category: render sub-theme pills ----
  function setCategory(catKey) {
    _currentCat = catKey;
    // Update cat tab active state
    document.querySelectorAll('.ct-cat-btn').forEach(function(b) {
      b.classList.toggle('ct-active', b.dataset.cat === catKey);
    });
    // Render pills
    var row2 = document.getElementById('ct-row2');
    if (!row2) return;
    row2.innerHTML = '';
    Object.keys(_CARD_THEMES).forEach(function(slug) {
      var t = _CARD_THEMES[slug];
      if (t.category !== catKey) return;
      var btn = document.createElement('button');
      btn.className = 'ct-pill' + (slug === _currentTheme ? ' ct-active' : '');
      btn.dataset.slug = slug;
      btn.textContent = t.name;
      btn.title = t.description || t.name;
      btn.onclick = function() { applyTheme(slug); };
      row2.appendChild(btn);
    });
  }

  // ---- Render category tabs ----
  function renderCats() {
    var container = document.getElementById('ct-cats');
    if (!container) return;
    container.innerHTML = '';
    _CARD_CATS.forEach(function(c) {
      var btn = document.createElement('button');
      btn.className = 'ct-cat-btn';
      btn.dataset.cat = c.key;
      btn.textContent = c.emoji + ' ' + c.key;
      btn.onclick = function() {
        setCategory(c.key);
        // Apply first theme in this category
        var first = Object.keys(_CARD_THEMES).find(function(s) {
          return _CARD_THEMES[s].category === c.key;
        });
        if (first) applyTheme(first);
      };
      container.appendChild(btn);
    });
  }

  // ---- Font size ----
  function initFontSize() {
    document.querySelectorAll('.ct-sz-btn').forEach(function(btn) {
      btn.onclick = function() {
        document.querySelectorAll('.ct-sz-btn').forEach(function(b) { b.classList.remove('ct-active'); });
        btn.classList.add('ct-active');
        document.body.style.fontSize = btn.dataset.size + 'px';
      };
    });
  }

  // ---- Viewport toggle ----
  function initViewport() {
    var mBtn = document.getElementById('ct-mobile');
    var pBtn = document.getElementById('ct-pc');
    if (!mBtn || !pBtn) return;
    mBtn.onclick = function() {
      document.body.classList.remove('vp-pc');
      document.body.classList.add('vp-mobile');
      mBtn.classList.add('ct-active');
      pBtn.classList.remove('ct-active');
    };
    pBtn.onclick = function() {
      document.body.classList.remove('vp-mobile');
      document.body.classList.add('vp-pc');
      pBtn.classList.add('ct-active');
      mBtn.classList.remove('ct-active');
    };
  }

  // ---- Export / screenshot ----
  function initExport() {
    var btn = document.getElementById('ct-export');
    if (!btn) return;
    btn.onclick = function() {
      var toolbar = document.getElementById('card-toolbar');
      var prevPT = document.body.style.paddingTop;
      if (toolbar) toolbar.style.display = 'none';
      document.body.style.paddingTop = '0';
      window.html2canvas(document.body, {
        scale: 2,
        useCORS: true,
        allowTaint: true,
        scrollY: 0,
        windowHeight: document.body.scrollHeight,
      }).then(function(canvas) {
        var link = document.createElement('a');
        link.download = 'inFlow-card-' + _currentTheme + '.png';
        link.href = canvas.toDataURL('image/png');
        link.click();
      }).finally(function() {
        if (toolbar) toolbar.style.display = '';
        document.body.style.paddingTop = prevPT;
      });
    };
  }

  // ---- Playwright helpers (exposed on window) ----
  window.applyTheme = applyTheme;
  window.hideToolbar = function() {
    var t = document.getElementById('card-toolbar');
    if (t) t.style.display = 'none';
    document.body.style.paddingTop = '0';
  };
  window.showToolbar = function() {
    var t = document.getElementById('card-toolbar');
    if (t) t.style.display = '';
    document.body.style.paddingTop = '76px';
  };

  // ---- Init on DOMContentLoaded ----
  function init() {
    renderCats();
    // Find the category of the initial theme
    var t = _CARD_THEMES[_currentTheme];
    var initCat = (t && t.category) || _CARD_CATS[0].key;
    setCategory(initCat);
    applyTheme(_currentTheme);
    initFontSize();
    initViewport();
    initExport();
    // Default: mobile viewport
    document.body.classList.add('vp-mobile');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""
