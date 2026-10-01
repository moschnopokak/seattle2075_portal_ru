// Проверка кода интерфейса. Файлы в static/js это обычные скрипты, которые делят общие глобальные имена,
// поэтому имена верхнего уровня собираются из самих файлов: опечатка в имени функции будет поймана (no-undef).
const fs = require("node:fs");
const path = require("node:path");
const js = require("@eslint/js");
const globals = require("globals");

const dir = path.join(__dirname, "static", "js");

// Имена из одной строки объявления вида: let S=null, V='gm', CFG={}, f=()=>{...};
function declaredNames(line) {
  const names = [];
  let depth = 0, quote = null, start = line.search(/\s/) + 1, part = "";
  const flush = () => {
    const m = part.trim().match(/^([A-Za-z_$][\w$]*)\s*(=|$)/);
    if (m) names.push(m[1]);
    else {
      const d = part.trim().match(/^[[{]([^\]}]*)[\]}]\s*=/);   // деструктуризация
      if (d) for (const n of d[1].split(",")) if (/^\s*[A-Za-z_$][\w$]*\s*$/.test(n)) names.push(n.trim());
    }
    part = "";
  };
  for (let i = start; i < line.length; i++) {
    const ch = line[i];
    if (quote) {
      part += ch;
      if (ch === "\\") { part += line[++i] || ""; } else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === "`") { quote = ch; part += ch; continue; }
    if ("([{".includes(ch)) depth++;
    if (")]}".includes(ch)) depth--;
    if (ch === ";" && depth === 0) break;
    if (ch === "," && depth === 0) { flush(); continue; }
    part += ch;
  }
  flush();
  return names;
}

const shared = {};
for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".js"))) {
  for (const line of fs.readFileSync(path.join(dir, file), "utf8").split("\n")) {
    const fn = line.match(/^(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)/);
    if (fn) { shared[fn[1]] = "writable"; continue; }
    if (/^(?:const|let|var)\s/.test(line)) for (const n of declaredNames(line)) shared[n] = "writable";
  }
}

module.exports = [
  { ignores: ["static/vendor/**", "node_modules/**"] },
  js.configs.recommended,
  {
    files: ["static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser, ...shared, module: "readonly", L: "readonly", Telegram: "readonly" },
    },
    rules: {
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "no-undef": "error",
      "no-redeclare": "off",              // имена верхнего уровня объявлены и здесь, и в списке общих имён
      "no-unused-vars": ["warn", { vars: "local", args: "none", caughtErrors: "none" }],
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-prototype-builtins": "off",
      "no-inner-declarations": "off",
      "no-cond-assign": ["error", "except-parens"],
      "no-useless-assignment": "off",     // начальные значения-страховки вроде let f='' намеренные
    },
  },
  {
    files: ["tests/js/**/*.js", "eslint.config.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "commonjs", globals: { ...globals.node } },
  },
];
