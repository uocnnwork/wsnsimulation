import numpy as np
import pandas as pd


class RicianChannelModel:
    """Indoor Rician Fading channel model backed by a pre-computed LUT.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5

    Collision model:
    Trong thực tế BLE/IEEE 802.15.4, khi nhiều node phát đồng thời trên cùng
    kênh, xác suất collision tăng theo số lượng transmitter đồng thời.
    success_prob *= collision_penalty ^ n_interferers
    """

    def __init__(self, lut_path: str, collision_penalty: float = 0.85):
        """
        collision_penalty: hệ số giảm success_prob cho mỗi interferer đồng thời.
                           0.85 ≈ thực nghiệm BLE Mesh indoor.
                           1.0  = tắt collision model (lý tưởng).
        """
        try:
            df = pd.read_csv(lut_path)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Rician LUT file not found: '{lut_path}'. "
                "Please provide a valid path via settings.LUT_PATH."
            )

        missing = {"Distance_m", "Success_Prob"} - set(df.columns)
        if missing:
            raise ValueError(f"LUT CSV is missing columns: {missing}")

        self._distances: np.ndarray = df["Distance_m"].to_numpy(dtype=float)
        self._probs: np.ndarray     = df["Success_Prob"].to_numpy(dtype=float)
        self._collision_penalty: float = collision_penalty

    def get_success_prob(self, distance: float) -> float:
        """Return success probability for distance via linear interpolation.

        Returns 0.0 when distance exceeds the maximum value in the LUT.
        Requirements: 3.3, 3.4
        """
        if distance > self._distances[-1]:
            return 0.0
        return float(np.interp(distance, self._distances, self._probs))

    def transmit(self, distance: float, concurrent_tx: int = 1) -> bool:
        """Simulate one transmission attempt.

        concurrent_tx: jumlah transmitter aktif di sekitar receiver pada saat ini,
                       termasuk sender ini sendiri. Default = 1 (no collision).

        Requirements: 3.5
        """
        base_prob = self.get_success_prob(distance)
        # n_interferers = concurrent transmitters selain sender sendiri
        n_interferers = max(0, concurrent_tx - 1)
        effective_prob = base_prob * (self._collision_penalty ** n_interferers)
        return bool(np.random.random() < effective_prob)
