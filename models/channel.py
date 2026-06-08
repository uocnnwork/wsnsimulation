import numpy as np
import pandas as pd


class RicianChannelModel:
    """Indoor Rician Fading channel model backed by a pre-computed LUT.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    """

    def __init__(self, lut_path: str):
        """Load the LUT from *lut_path*.

        Raises:
            FileNotFoundError: if the file does not exist.
            ValueError: if required columns are missing.
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
        self._probs: np.ndarray = df["Success_Prob"].to_numpy(dtype=float)

    def get_success_prob(self, distance: float) -> float:
        """Return the success probability for *distance* via linear interpolation.

        Returns 0.0 when distance exceeds the maximum value in the LUT.
        Requirements: 3.3, 3.4
        """
        if distance > self._distances[-1]:
            return 0.0
        return float(np.interp(distance, self._distances, self._probs))

    def transmit(self, distance: float) -> bool:
        """Simulate one transmission attempt at *distance*.

        Returns True on success, False on failure.
        Requirements: 3.5
        """
        prob = self.get_success_prob(distance)
        return bool(np.random.random() < prob)
