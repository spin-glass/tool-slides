-- 1. <!-- appendix --> より後のスライドに appendix クラスを付ける（テーマがタイトルの上に「付録」と出す）。
--    コメントは出力に残らないので、印が無いと聴衆には本編の続きに見える。
-- 2. HTML コメントだけの段落（<!-- budget: 4 --> などの lint 用メタ・evidence・appendix 印）を出力から除く。
--    最初の見出しより前に残ると revealjs で空のスライドになるため。
local function mark_appendix(doc)
  local after = false
  for _, b in ipairs(doc.blocks) do
    if b.t == "RawBlock" and b.format:match("html") and b.text:match("<!%-%-%s*appendix%s*%-%->") then
      after = true
    elseif after and b.t == "Header" and b.level == 2 then
      b.classes:insert("appendix")
    end
  end
  return doc
end

local function strip_comments(el)
  if el.format:match("html") and el.text:match("^%s*<!%-%-.-%-%->%s*$") then
    -- 複数コメントが連続する場合も全体がコメントならまとめて消す
    local rest = el.text:gsub("<!%-%-.-%-%->", ""):gsub("%s", "")
    if rest == "" then
      return {}
    end
  end
end

return { { Pandoc = mark_appendix }, { RawBlock = strip_comments } }
