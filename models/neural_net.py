"""
PyTorch neural network for head-to-head cycling prediction.
"""

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


class CyclingNet(nn.Module):
    """
    Feed-forward neural network for H2H prediction.

    Architecture: Input → [Dense → BatchNorm → ReLU → Dropout] × N → Sigmoid
    """

    def __init__(self, input_dim: int, hidden_dims: list[int] = None, dropout: float = 0.3):
        super().__init__()

        if hidden_dims is None:
            hidden_dims = [256, 128, 64, 32]

        layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            layers.extend([
                nn.Linear(prev_dim, h_dim),
                nn.BatchNorm1d(h_dim),
                nn.ReLU(),
                nn.Dropout(dropout),
            ])
            prev_dim = h_dim

        layers.append(nn.Linear(prev_dim, 1))
        layers.append(nn.Sigmoid())

        self.network = nn.Sequential(*layers)

    def forward(self, x):
        return self.network(x).squeeze(-1)


def train_neural_net(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    hidden_dims: list[int] = None,
    dropout: float = 0.3,
    lr: float = 1e-3,
    batch_size: int = 512,
    epochs: int = 100,
    patience: int = 10,
) -> tuple:
    """
    Train the neural network with early stopping.

    Returns (model, history_dict).
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    X_train_t = torch.FloatTensor(X_train).to(device)
    y_train_t = torch.FloatTensor(y_train).to(device)
    X_val_t = torch.FloatTensor(X_val).to(device)
    y_val_t = torch.FloatTensor(y_val).to(device)

    train_ds = TensorDataset(X_train_t, y_train_t)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

    input_dim = X_train.shape[1]
    model = CyclingNet(input_dim, hidden_dims, dropout).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=5,
    )
    criterion = nn.BCELoss()

    history = {"train_loss": [], "val_loss": [], "val_acc": []}
    best_val_loss = float("inf")
    best_state = None
    wait = 0

    for epoch in range(epochs):
        # Train
        model.train()
        train_losses = []
        for xb, yb in train_loader:
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())

        # Validate
        model.eval()
        with torch.no_grad():
            val_pred = model(X_val_t)
            val_loss = criterion(val_pred, y_val_t).item()
            val_acc = ((val_pred >= 0.5).float() == y_val_t).float().mean().item()

        avg_train_loss = np.mean(train_losses)
        history["train_loss"].append(avg_train_loss)
        history["val_loss"].append(val_loss)
        history["val_acc"].append(val_acc)

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                print(f"  Early stopping at epoch {epoch + 1}")
                break

        if (epoch + 1) % 10 == 0:
            print(f"  Epoch {epoch+1}: train_loss={avg_train_loss:.4f} "
                  f"val_loss={val_loss:.4f} val_acc={val_acc:.4f}")

    if best_state:
        model.load_state_dict(best_state)

    model.eval()
    return model, history


def predict_neural_net(model: CyclingNet, X: np.ndarray) -> np.ndarray:
    """Run prediction with trained model."""
    device = next(model.parameters()).device
    model.eval()
    with torch.no_grad():
        X_t = torch.FloatTensor(X).to(device)
        probs = model(X_t).cpu().numpy()
    return probs
