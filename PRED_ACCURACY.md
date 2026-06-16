# 🎯 本屆世界盃「正式預測」即時準確度

_更新:2026-06-16 12:02:29　已評估場次:16_

> ⚠️ 樣本極小,以下數字僅供參考,**不應據此調整回測校準過的參數**(會 overfit)。

## 總指標

- 1X2 命中率:**38%**（6/16）
- RPS：**0.202**（越低越好;隨機基準 0.194）
- Brier：0.752　Log-loss：1.213
- 精確比分命中率：6%　進球差 MAE：2.00　總進球 MAE：1.38

> RPS 0.202 vs 隨機 0.194 → **尚未優於隨機**。

## 逐場

| # | 對戰 | 預測(主/和/客) | 預測比分 | 實際 | 1X2 | 比分 |
|---|---|---|---|---|---|---|
| 1 | Mexico vs South Africa | 69/16/15 | 3-0 | 2-0 | ✅ | — |
| 2 | South Korea vs Czechia | 39/31/30 | 2-1 | 2-1 | ✅ | ✅ |
| 7 | Canada vs Bosnia-Herzegovina | 59/22/18 | 2-0 | 1-1 | ❌ | — |
| 8 | Qatar vs Switzerland | 14/14/72 | 0-4 | 1-1 | ❌ | — |
| 13 | Brazil vs Morocco | 42/27/32 | 2-1 | 1-1 | ❌ | — |
| 14 | Haiti vs Scotland | 18/22/60 | 0-2 | 0-1 | ✅ | — |
| 19 | USA vs Paraguay | 45/29/26 | 2-1 | 4-1 | ✅ | — |
| 20 | Australia vs Türkiye | 23/28/49 | 1-2 | 2-0 | ❌ | — |
| 25 | Germany vs Curaçao | 74/12/14 | 6-0 | 7-1 | ✅ | — |
| 26 | Ivory Coast vs Ecuador | 25/26/50 | 1-2 | 1-0 | ❌ | — |
| 31 | Netherlands vs Japan | 44/26/30 | 2-1 | 2-2 | ❌ | — |
| 32 | Sweden vs Tunisia | 47/28/24 | 2-1 | 5-1 | ✅ | — |
| 37 | Belgium vs Egypt | 52/26/22 | 2-0 | 1-1 | ❌ | — |
| 38 | Iran vs New Zealand | 68/17/15 | 3-0 | 2-2 | ❌ | — |
| 43 | Spain vs Cape Verde | 73/14/14 | 5-0 | 0-0 | ❌ | — |
| 44 | Saudi Arabia vs Uruguay | 16/19/65 | 0-2 | 1-1 | ❌ | — |

## 逐場差異與原因

- **#1 Mexico vs South Africa**：✅ 命中:模型賽前看好主勝（Mexico 69%，高信心），結果如預期。
- **#2 South Korea vs Czechia**：✅ 命中:模型賽前看好主勝（South Korea 39%，低信心），結果如預期。
- **#7 Canada vs Bosnia-Herzegovina**：❌ 模型看好Canada贏，最後雙方言和；模型其實也給了和局 22%。
- **#8 Qatar vs Switzerland**：❌ 模型看好Switzerland贏，最後雙方言和；模型其實也給了和局 14%；大冷門:模型高度看好仍翻盤,多為紅牌/定位球/門將神勇等臨場因素。
- **#13 Brazil vs Morocco**：❌ 模型看好Brazil贏，最後雙方言和；模型其實也給了和局 27%；合理變異:三方接近(主42/和27/客32),模型信心本就低；兩隊實力接近(Elo 僅差 4)。
- **#14 Haiti vs Scotland**：✅ 命中:模型賽前看好客勝（Scotland 60%，中信心），結果如預期。
- **#19 USA vs Paraguay**：✅ 命中:模型賽前看好主勝（USA 45%，低信心），結果如預期。
- **#20 Australia vs Türkiye**：❌ 模型看好Türkiye（49%），最後由Australia勝出。
- **#25 Germany vs Curaçao**：✅ 命中:模型賽前看好主勝（Germany 74%，高信心），結果如預期。
- **#26 Ivory Coast vs Ecuador**：❌ 模型看好Ecuador（50%），最後由Ivory Coast勝出。
- **#31 Netherlands vs Japan**：❌ 模型看好Netherlands贏，最後雙方言和；模型其實也給了和局 26%；合理變異:三方接近(主44/和26/客30),模型信心本就低；兩隊實力接近(Elo 僅差 20)。
- **#32 Sweden vs Tunisia**：✅ 命中:模型賽前看好主勝（Sweden 47%，中信心），結果如預期。
- **#37 Belgium vs Egypt**：❌ 模型看好Belgium贏，最後雙方言和；模型其實也給了和局 26%。
- **#38 Iran vs New Zealand**：❌ 模型看好Iran贏，最後雙方言和；模型其實也給了和局 17%；大冷門:模型高度看好仍翻盤,多為紅牌/定位球/門將神勇等臨場因素。
- **#43 Spain vs Cape Verde**：❌ 模型看好Spain贏，最後雙方言和；模型其實也給了和局 14%；大冷門:模型高度看好仍翻盤,多為紅牌/定位球/門將神勇等臨場因素。
- **#44 Saudi Arabia vs Uruguay**：❌ 模型看好Uruguay贏，最後雙方言和；模型其實也給了和局 19%；大冷門:模型高度看好仍翻盤,多為紅牌/定位球/門將神勇等臨場因素。

