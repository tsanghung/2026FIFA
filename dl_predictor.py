import os
import sys
import math
import random
import sqlite3
import numpy as np
from datetime import datetime

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import KFold

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dl_model.pth')
SCALER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dl_scaler.npz')

FEATURE_NAMES = [
    '主隊 Elo', '主隊 FIFA排名', '主隊 Pi(主場)', '主隊 Pi(客場)',
    '主隊 Berrar攻', '主隊 Berrar防', '主隊 xG差', '主隊傷兵數',
    '主隊輿情指數', '主隊 Opta勝率',
    '客隊 Elo', '客隊 FIFA排名', '客隊 Pi(客場)', '客隊 Pi(主場)',
    '客隊 Berrar攻', '客隊 Berrar防', '客隊 xG差', '客隊傷兵數',
    '客隊輿情指數', '客隊 Opta勝率',
    'Elo差', '排名差', 'Pi差', '主隊攻防比',
    '客隊攻防比', 'xG差', '傷兵差', '輿情差',
    'Opta差', '平均Elo', '總攻擊力', '總防守力',
    '集成主勝率', '集成和局率', '集成客勝率',
    '集成主隊xG', '集成客隊xG', '總xG',
    '賠率-主勝', '賠率-和局', '賠率-客勝',
]


def get_team_features_dict(cursor, team_name, is_home=True):
    cursor.execute('''
        SELECT elo_rating, fifa_rank, pi_rating_home, pi_rating_away,
               berrar_att, berrar_def, fbref_xg_diff, injury_count,
               sentiment_score, opta_win_prob
        FROM teams WHERE name = ?
    ''', (team_name,))
    row = cursor.fetchone()
    if not row:
        return {
            'elo_rating': 1400.0, 'fifa_rank': 50, 'pi_rating_home': 0.0,
            'pi_rating_away': 0.0, 'berrar_att': 1.0, 'berrar_def': 1.0,
            'fbref_xg_diff': 0.0, 'injury_count': 0, 'sentiment_score': 0.0,
            'opta_win_prob': 0.001
        }
    return {
        'elo_rating': row[0] or 1400.0,
        'fifa_rank': row[1] or 50,
        'pi_rating_home': row[2] or 0.0,
        'pi_rating_away': row[3] or 0.0,
        'berrar_att': row[4] or 1.0,
        'berrar_def': row[5] or 1.0,
        'fbref_xg_diff': row[6] or 0.0,
        'injury_count': row[7] or 0,
        'sentiment_score': row[8] or 0.0,
        'opta_win_prob': row[9] or 0.001
    }


def build_match_features(cursor, match_row):
    (match_num, home, away, status, home_goals, away_goals,
     pred_home_win, pred_draw, pred_away,
     pred_home_xg, pred_away_xg, pred_score,
     odds_home, odds_draw, odds_away) = match_row

    h_feat = get_team_features_dict(cursor, home, is_home=True)
    a_feat = get_team_features_dict(cursor, away, is_home=False)

    features = [
        h_feat['elo_rating'], h_feat['fifa_rank'], h_feat['pi_rating_home'],
        h_feat['pi_rating_away'], h_feat['berrar_att'], h_feat['berrar_def'],
        h_feat['fbref_xg_diff'], h_feat['injury_count'], h_feat['sentiment_score'],
        h_feat['opta_win_prob'],
        a_feat['elo_rating'], a_feat['fifa_rank'], a_feat['pi_rating_away'],
        a_feat['pi_rating_home'], a_feat['berrar_att'], a_feat['berrar_def'],
        a_feat['fbref_xg_diff'], a_feat['injury_count'], a_feat['sentiment_score'],
        a_feat['opta_win_prob'],
        h_feat['elo_rating'] - a_feat['elo_rating'],
        h_feat['fifa_rank'] - a_feat['fifa_rank'],
        h_feat['pi_rating_home'] - a_feat['pi_rating_away'],
        h_feat['berrar_att'] / max(a_feat['berrar_def'], 0.1),
        a_feat['berrar_att'] / max(h_feat['berrar_def'], 0.1),
        h_feat['fbref_xg_diff'] - a_feat['fbref_xg_diff'],
        h_feat['injury_count'] - a_feat['injury_count'],
        h_feat['sentiment_score'] - a_feat['sentiment_score'],
        h_feat['opta_win_prob'] - a_feat['opta_win_prob'],
        (h_feat['elo_rating'] + a_feat['elo_rating']) / 2,
        h_feat['berrar_att'] + a_feat['berrar_att'],
        h_feat['berrar_def'] + a_feat['berrar_def'],
        pred_home_win or 0.33,
        pred_draw or 0.33,
        pred_away or 0.33,
        pred_home_xg or 1.25,
        pred_away_xg or 1.05,
        (pred_home_xg or 1.25) + (pred_away_xg or 1.05),
        odds_home or 2.5,
        odds_draw or 3.3,
        odds_away or 2.8,
    ]

    return np.array(features, dtype=np.float32)


def get_label(match_row):
    home_goals = match_row[4]
    away_goals = match_row[5]
    if home_goals is None or away_goals is None:
        return None, None, None
    if home_goals > away_goals:
        label = 0
    elif home_goals == away_goals:
        label = 1
    else:
        label = 2
    return label, float(home_goals), float(away_goals)


class WorldCupPredictor(nn.Module):
    def __init__(self, input_dim=41, dropout_rate=0.3):
        super(WorldCupPredictor, self).__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(256, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(128, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(dropout_rate * 0.7),
            nn.Linear(64, 32),
            nn.ReLU(),
        )
        self.classifier = nn.Sequential(
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 3),
        )
        self.regressor = nn.Sequential(
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 2),
            nn.ReLU(),
        )

    def forward(self, x):
        shared_out = self.shared(x)
        class_logits = self.classifier(shared_out)
        goal_pred = self.regressor(shared_out)
        return class_logits, goal_pred

    def predict_proba_mc(self, x, n_samples=100):
        self.train()
        probs_list = []
        with torch.no_grad():
            for _ in range(n_samples):
                logits, _ = self.forward(x)
                probs = torch.softmax(logits, dim=1)
                probs_list.append(probs)
        self.eval()
        probs_stack = torch.stack(probs_list)
        mean_probs = probs_stack.mean(dim=0)
        std_probs = probs_stack.std(dim=0)
        return mean_probs, std_probs


class MatchDataset(Dataset):
    def __init__(self, features, labels, goal_labels=None):
        self.features = torch.FloatTensor(features)
        self.labels = torch.LongTensor(labels) if labels is not None else None
        self.goal_labels = torch.FloatTensor(goal_labels) if goal_labels is not None else None

    def __len__(self):
        return len(self.features)

    def __getitem__(self, idx):
        item = {'features': self.features[idx]}
        if self.labels is not None:
            item['labels'] = self.labels[idx]
        if self.goal_labels is not None:
            item['goals'] = self.goal_labels[idx]
        return item


def load_training_data(db_path=None):
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.match_num, m.home_team, m.away_team, m.status,
               m.home_goals, m.away_goals,
               m.pred_home_win_prob, m.pred_draw_prob, m.pred_away_win_prob,
               m.pred_home_expected_goals, m.pred_away_expected_goals, m.pred_score,
               m.odds_home, m.odds_draw, m.odds_away
        FROM matches m
        WHERE m.status = 'Completed'
          AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL
        ORDER BY m.match_num ASC
    ''')
    completed_matches = cursor.fetchall()
    features_list = []
    labels_list = []
    goals_list = []
    for match in completed_matches:
        feat = build_match_features(cursor, match)
        label, h_goals, a_goals = get_label(match)
        if label is not None:
            features_list.append(feat)
            labels_list.append(label)
            goals_list.append([h_goals, a_goals])
    conn.close()
    if len(features_list) == 0:
        return None, None, None, len(completed_matches)
    return (np.array(features_list, dtype=np.float32),
            np.array(labels_list, dtype=np.int64),
            np.array(goals_list, dtype=np.float32),
            len(completed_matches))


def load_all_match_features(db_path=None):
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.match_num, m.home_team, m.away_team, m.status,
               m.home_goals, m.away_goals,
               m.pred_home_win_prob, m.pred_draw_prob, m.pred_away_win_prob,
               m.pred_home_expected_goals, m.pred_away_expected_goals, m.pred_score,
               m.odds_home, m.odds_draw, m.odds_away
        FROM matches m
        ORDER BY m.match_num ASC
    ''')
    all_matches = cursor.fetchall()
    match_info = []
    features_list = []
    for match in all_matches:
        feat = build_match_features(cursor, match)
        features_list.append(feat)
        match_info.append({
            'match_num': match[0],
            'home_team': match[1],
            'away_team': match[2],
            'status': match[3],
            'home_goals': match[4],
            'away_goals': match[5],
        })
    conn.close()
    return np.array(features_list, dtype=np.float32), match_info


def train_model(n_epochs=200, batch_size=8, learning_rate=0.001,
                weight_decay=1e-4, k_folds=3, progress_callback=None):
    X, y, goals, total_completed = load_training_data()
    if X is None or len(X) < 5:
        return None, None, {
            'error': f'訓練數據不足 (僅 {total_completed} 場完賽)，請先同步更多完賽數據。',
            'total_completed': total_completed or 0
        }

    if len(X) < 30:
        noise_factor = 0.02
        augmented_X = X.copy()
        augmented_y = y.copy()
        augmented_goals = goals.copy()
        for _ in range(3):
            noise = np.random.normal(0, noise_factor, X.shape).astype(np.float32)
            augmented_X = np.vstack([augmented_X, X + noise])
            augmented_y = np.concatenate([augmented_y, y])
            augmented_goals = np.vstack([augmented_goals, goals])
        X, y, goals = augmented_X, augmented_y, augmented_goals

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X).astype(np.float32)

    n_splits = min(k_folds, max(2, len(X) // 5))
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)

    best_model_state = None
    best_loss = float('inf')
    history = {'train_loss': [], 'val_loss': [], 'accuracy': [], 'fold': []}
    input_dim = X_scaled.shape[1]

    for fold, (train_idx, val_idx) in enumerate(kf.split(X_scaled)):
        X_train, X_val = X_scaled[train_idx], X_scaled[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        g_train, g_val = goals[train_idx], goals[val_idx]

        train_dataset = MatchDataset(X_train, y_train, g_train)
        val_dataset = MatchDataset(X_val, y_val, g_val)
        train_loader = DataLoader(train_dataset, batch_size=min(batch_size, len(train_dataset)), shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=min(batch_size, max(1, len(val_dataset))))

        model = WorldCupPredictor(input_dim=input_dim, dropout_rate=0.3)
        optimizer = optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
        criterion_cls = nn.CrossEntropyLoss()
        criterion_reg = nn.MSELoss()

        fold_best_loss = float('inf')
        patience_counter = 0
        patience = 30

        for epoch in range(n_epochs):
            model.train()
            train_loss = 0.0
            for batch in train_loader:
                feats = batch['features']
                labels = batch['labels']
                g_targets = batch['goals']
                optimizer.zero_grad()
                logits, goal_pred = model(feats)
                loss_cls = criterion_cls(logits, labels)
                loss_reg = criterion_reg(goal_pred, g_targets)
                loss = 0.7 * loss_cls + 0.3 * loss_reg
                loss.backward()
                optimizer.step()
                train_loss += loss.item()
            scheduler.step()

            model.eval()
            val_loss = 0.0
            correct = 0
            with torch.no_grad():
                for batch in val_loader:
                    feats = batch['features']
                    labels = batch['labels']
                    g_targets = batch['goals']
                    logits, goal_pred = model(feats)
                    loss_cls = criterion_cls(logits, labels)
                    loss_reg = criterion_reg(goal_pred, g_targets)
                    loss = 0.7 * loss_cls + 0.3 * loss_reg
                    val_loss += loss.item()
                    pred_labels = torch.argmax(logits, dim=1)
                    correct += (pred_labels == labels).sum().item()

            avg_train_loss = train_loss / len(train_loader)
            avg_val_loss = val_loss / len(val_loader)
            accuracy = correct / len(val_dataset) if len(val_dataset) > 0 else 0

            history['train_loss'].append(avg_train_loss)
            history['val_loss'].append(avg_val_loss)
            history['accuracy'].append(accuracy)
            history['fold'].append(fold)

            if progress_callback:
                progress_callback(fold, epoch, n_epochs, avg_train_loss, avg_val_loss, accuracy)

            if avg_val_loss < fold_best_loss:
                fold_best_loss = avg_val_loss
                if fold_best_loss < best_loss:
                    best_loss = fold_best_loss
                    best_model_state = {k: v.clone() for k, v in model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

    final_model = WorldCupPredictor(input_dim=input_dim, dropout_rate=0.3)
    if best_model_state is not None:
        final_model.load_state_dict(best_model_state)

    np.savez(SCALER_PATH,
             mean=scaler.mean_,
             scale=scaler.scale_,
             var=scaler.var_,
             n_features_in=scaler.n_features_in_,
             n_samples_seen=scaler.n_samples_seen_)

    torch.save({
        'model_state_dict': best_model_state,
        'input_dim': input_dim,
        'n_completed': len(y),
    }, MODEL_PATH)

    final_history = {
        'train_loss': history['train_loss'],
        'val_loss': history['val_loss'],
        'accuracy': history['accuracy'],
        'best_val_loss': best_loss,
        'n_training_samples': len(y),
        'n_completed_matches': total_completed,
        'input_dim': input_dim,
    }
    return final_model, scaler, final_history


def predict_all_matches(db_path=None, n_mc_samples=100):
    if db_path is None:
        db_path = DB_PATH
    if not os.path.exists(MODEL_PATH):
        return None, "模型尚未訓練。請先點擊「訓練模型」按鈕。"

    checkpoint = torch.load(MODEL_PATH, weights_only=False)
    input_dim = checkpoint['input_dim']
    model = WorldCupPredictor(input_dim=input_dim, dropout_rate=0.3)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    if not os.path.exists(SCALER_PATH):
        return None, "特徵縮放器不存在，請重新訓練模型。"

    scaler_data = np.load(SCALER_PATH)
    scaler = StandardScaler()
    scaler.mean_ = scaler_data['mean']
    scaler.scale_ = scaler_data['scale']
    scaler.var_ = scaler_data['var']
    scaler.n_features_in_ = int(scaler_data['n_features_in'])
    scaler.n_samples_seen_ = int(scaler_data['n_samples_seen'])

    X, match_info = load_all_match_features(db_path)
    X_scaled = scaler.transform(X).astype(np.float32)
    X_tensor = torch.FloatTensor(X_scaled)

    mean_probs, std_probs = model.predict_proba_mc(X_tensor, n_samples=n_mc_samples)

    with torch.no_grad():
        _, goal_preds = model(X_tensor)
        goal_preds = goal_preds.numpy()

    results = []
    label_names = ['主勝 (Home Win)', '和局 (Draw)', '客勝 (Away Win)']

    for i, info in enumerate(match_info):
        probs = mean_probs[i].numpy()
        stds = std_probs[i].numpy()
        goals = goal_preds[i]
        pred_label = int(np.argmax(probs))
        confidence = float(probs[pred_label])
        uncertainty = float(stds[pred_label])

        if confidence > 0.55 and uncertainty < 0.08:
            conf_level = "HIGH"
        elif confidence > 0.40 and uncertainty < 0.12:
            conf_level = "MEDIUM"
        else:
            conf_level = "LOW"

        pred_home_goals = round(max(0, goals[0]), 1)
        pred_away_goals = round(max(0, goals[1]), 1)
        pred_score = f"{int(round(pred_home_goals))}-{int(round(pred_away_goals))}"

        results.append({
            'match_num': info['match_num'],
            'home_team': info['home_team'],
            'away_team': info['away_team'],
            'status': info['status'],
            'home_win_prob': float(probs[0]),
            'draw_prob': float(probs[1]),
            'away_win_prob': float(probs[2]),
            'home_win_std': float(stds[0]),
            'draw_std': float(stds[1]),
            'away_win_std': float(stds[2]),
            'predicted_label': pred_label,
            'predicted_outcome': label_names[pred_label],
            'confidence': confidence,
            'uncertainty': uncertainty,
            'confidence_level': conf_level,
            'pred_home_goals': pred_home_goals,
            'pred_away_goals': pred_away_goals,
            'pred_score': pred_score,
            'home_goals_actual': info['home_goals'],
            'away_goals_actual': info['away_goals'],
        })

    return results, None


def get_feature_importance(match_features_scaled, model):
    model.eval()
    x = torch.FloatTensor(match_features_scaled.reshape(1, -1))
    x.requires_grad = True
    logits, _ = model(x)
    probs = torch.softmax(logits, dim=0)
    pred_class = torch.argmax(probs)
    probs[pred_class].backward()
    importance = x.grad.abs().squeeze().detach().numpy()
    feat_imp = []
    for j in range(min(len(importance), len(FEATURE_NAMES))):
        feat_imp.append((FEATURE_NAMES[j], float(importance[j])))
    feat_imp.sort(key=lambda x: x[1], reverse=True)
    return feat_imp[:10]


def main():
    print("=" * 70)
    print("  2026 FIFA 世界盃 Deep Learning 預測引擎")
    print("=" * 70)
    print("\n[1] 訓練模型")
    print("[2] 預測所有賽事")
    print("[3] 訓練 + 預測")
    choice = input("\n請選擇 (1-3): ").strip()

    if choice in ['1', '3']:
        print("\n開始訓練模型...")
        def progress_cb(fold, epoch, total, train_loss, val_loss, acc):
            if epoch % 20 == 0:
                print(f"  Fold {fold} | Epoch {epoch}/{total} | "
                      f"Train: {train_loss:.4f} | Val: {val_loss:.4f} | Acc: {acc:.2%}")
        model, scaler, hist = train_model(progress_callback=progress_cb)
        if model is None:
            print(f"\n訓練失敗: {hist.get('error', '未知錯誤')}")
            return
        print(f"\n訓練完成！")
        print(f"  訓練樣本: {hist['n_training_samples']}")
        print(f"  最佳驗證損失: {hist['best_val_loss']:.4f}")
        print(f"  最終準確率: {hist['accuracy'][-1]:.2%}")

    if choice in ['2', '3']:
        print("\n開始預測所有賽事...")
        results, err = predict_all_matches()
        if err:
            print(f"預測失敗: {err}")
            return
        print(f"\n{'場次':<4} | {'對戰組合':<30} | {'AI預測':<18} | {'信心度':<8} | {'預測比分':<6}")
        print("-" * 80)
        for r in results:
            matchup = f"{r['home_team']} vs {r['away_team']}"
            conf_icon = {"HIGH": "[G]", "MEDIUM": "[M]", "LOW": "[L]"}.get(r['confidence_level'], "[?]")
            print(f"#{r['match_num']:<3} | {matchup:<30} | {r['predicted_outcome']:<18} | "
                  f"{conf_icon} {r['confidence']:.0%} | {r['pred_score']:<6}")


if __name__ == '__main__':
    main()
