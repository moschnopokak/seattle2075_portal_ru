// Тесты скачивания дневника (static/js/diary.js): имя файла из заголовка ответа.
const test = require("node:test");
const assert = require("node:assert/strict");
const diary = require("../../static/js/diary.js");

test("имя файла берётся из filename* и раскодируется", () => {
  assert.equal(diary.diaryName("attachment; filename=\"diary.md\"; filename*=UTF-8''%D0%94%D0%BD%D0%B5%D0%B2%D0%BD%D0%B8%D0%BA-%D0%A0%D0%B8%D0%B3-2075-08-01.md"), "Дневник-Риг-2075-08-01.md");
});

test("без filename* берётся обычное имя, без заголовка запасное", () => {
  assert.equal(diary.diaryName('attachment; filename="diary.pdf"'), "diary.pdf");
  assert.equal(diary.diaryName(""), "diary");
  assert.equal(diary.diaryName(null), "diary");
});

test("испорченное кодирование не роняет, остаётся обычное имя", () => {
  assert.equal(diary.diaryName("attachment; filename=\"diary.md\"; filename*=UTF-8''%E0%A4%A"), "diary.md");
});

test("части дневника и значения по умолчанию согласованы", () => {
  assert.ok(diary.DIARY_DEFAULT.every((k) => k in diary.DIARY_PARTS));
  assert.ok("chat" in diary.DIARY_PARTS && !diary.DIARY_DEFAULT.includes("chat"));          // обсуждения по умолчанию не включаются
});
