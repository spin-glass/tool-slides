-- 動きの有無（デッキの YAML の `motion`）。`motion: false` のデッキは、図解の部品（parts.*）を枚を開いたときに動かさず
-- 最終状態で出し、段階送り（fragment）もしない。theme/motion-gsap.html が window.SLIDES_MOTION を読む。
-- 書かない・`motion: true` は動きあり（既定）。pptx・beamer はもともと動かないので何もしない。
function Meta(meta)
  local v = meta.motion
  if v ~= nil and type(v) ~= "boolean" then
    v = pandoc.utils.stringify(v)
  end
  if (v == false or v == "false") and quarto.doc.is_format("revealjs") then
    quarto.doc.include_text("in-header", "<script>window.SLIDES_MOTION = false;</script>")
  end
end
