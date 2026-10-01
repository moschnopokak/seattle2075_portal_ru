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

// Скрипты делят одну глобальную область, поэтому одно и то же имя верхнего уровня в двух файлах (const или let) ломает
// второй файл целиком: браузер не запустит его вообще. Ловим это здесь, а не в браузере у пользователя.
const shared = {}, owner = {};
function declare(name, file) {
  if (owner[name]) throw new Error(`Имя «${name}» объявлено в двух местах верхнего уровня: static/js/${owner[name]} и static/js/${file}. Скрипты делят общую область, второй не загрузится.`);
  owner[name] = file;
  shared[name] = "writable";
}
for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".js"))) {
  for (const line of fs.readFileSync(path.join(dir, file), "utf8").split("\n")) {
    const fn = line.match(/^(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)/);
    if (fn) { declare(fn[1], file); continue; }
    if (/^(?:const|let|var)\s/.test(line)) for (const n of declaredNames(line)) declare(n, file);
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
