-- HTML コメントだけの段落（<!-- budget: 4 --> などの lint 用メタ・evidence・appendix 印）を出力から除く。
-- 最初の見出しより前に残ると revealjs で空のスライドになるため。
function RawBlock(el)
  if el.format:match("html") and el.text:match("^%s*<!%-%-.-%-%->%s*$") then
    -- 複数コメントが連続する場合も全体がコメントならまとめて消す
    local rest = el.text:gsub("<!%-%-.-%-%->", ""):gsub("%s", "")
    if rest == "" then
      return {}
    end
  end
end
