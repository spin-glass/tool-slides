-- 章ラベル（kicker）付きの短い見出し: `## 観測と判定を分ける {kicker="設計"}`
-- revealjs/html では見出しの中に <span class="kicker">設計</span> を入れ、テーマが見出しの上の小さな橙の行にする
-- （theme/custom.scss の .reveal h2 .kicker）。pptx・beamer では見出しの文字だけにする（章ラベルは落ちる。
-- 本文の `.lead` 行は残る）。属性 kicker 自体は出力に残さない。
-- 既定の様式（title-style: short）。完全文のタイトル（title-style: sentence）の枚はこの属性を書かない。
local function kicker(el)
  if el.level ~= 2 or not el.attributes or not el.attributes["kicker"] then
    return nil
  end
  local label = el.attributes["kicker"]
  el.attributes["kicker"] = nil
  if FORMAT:match("html") or FORMAT:match("revealjs") then
    local span = pandoc.Span(pandoc.Str(label), pandoc.Attr("", { "kicker" }))
    local content = pandoc.List({ span })
    content:extend(el.content)
    el.content = content
  end
  return el
end

return { { Header = kicker } }
