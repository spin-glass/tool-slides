# 同梱ライブラリ（版固定。更新は npm pack で取り直し、sha256 を書き換える）

| ファイル | 版 | ライセンス | sha256 |
|---|---|---|---|
| gsap.min.js | gsap 3.15.0（npm、2026-04-13） | GSAP Standard "No Charge" License（Webflow。無償・商用可だが OSI のオープンソースではない。ノーコードのアニメ作成ツールへの組み込みは不可） | 92bb9a96476f983d212a2bc4f54c889039c1696dd4461d40a736860938570fbb |
| echarts.min.js | echarts 6.1.0（npm、2026-05-19。全部入り。simple 版は値ラベルの数え上げ（label.valueAnimation）が動かないことを実測で確認） | Apache-2.0 | b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0 |
| DrawSVGPlugin.min.js / Flip.min.js | gsap 3.15.0 の同梱プラグイン（同じライセンス） | 同上 | DrawSVG beb19529…、Flip cbe3ca72…（`sha256sum theme/vendor/*.js` で確認） |
