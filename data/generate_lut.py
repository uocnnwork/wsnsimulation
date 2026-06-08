import numpy as np
import pandas as pd
import time
from scipy.signal import butter, filtfilt
from scipy.stats import ncx2

def db2pow(db):
    """Chuyển đổi dB sang tỷ lệ công suất tuyến tính"""
    return 10 ** (db / 10.0)

def pow2db(p):
    """Chuyển đổi tỷ lệ công suất tuyến tính sang dB"""
    return 10 * np.log10(p)

def receptionprob_rice(d, n=None):
    """
    Mô phỏng xác suất nhận thành công qua kênh Rician.
    """
    numpaths = 3
    Fc = 2500e6        # Tần số sóng mang (Carrier frequency)
    Fs = 4 * Fc        # Tần số lấy mẫu (Sampling frequency)
    Ts = 1 / Fs
    t = np.arange(0, 2000 * Ts, Ts) # Mảng thời gian
    wc = 2 * np.pi * Fc
    
    rice_signal = np.zeros(len(t))
    
    # 1. Tạo tín hiệu Multi-path
    for _ in range(numpaths - 1):
        a = 1 * np.random.weibull(3, len(t))
        phase = np.random.uniform(0, 2 * np.pi, len(t))
        rice_signal += a * np.cos(wc * t + phase)
        
    # Thêm thành phần Line Of Sight (LOS)
    rice_signal += 4.5 * np.cos(wc * t)
    
    # 2. Giải điều chế (Demodulation - QAM)
    I_mix = 2 * rice_signal * np.cos(wc * t)
    # Đã sửa lỗi đánh máy: np.np.sin -> np.sin
    Q_mix = -2 * rice_signal * np.sin(wc * t)
    
    # Bộ lọc thông thấp Butterworth bậc 5, tần số cắt tại Fc (chuẩn hóa Wn = 0.5)
    b_filt, a_filt = butter(5, 0.5)
    ricei = filtfilt(b_filt, a_filt, I_mix)
    riceq = filtfilt(b_filt, a_filt, Q_mix)
    
    # 3. Tính toán thông số kênh Rician
    env_rice = np.sqrt(ricei**2 + riceq**2)
    b = np.sqrt((np.var(ricei, ddof=1) + np.var(riceq, ddof=1)) / 2) 
    a_rician = np.mean(ricei)                                        
    
    mean_power = 10 * np.log10(np.mean(env_rice**2))
    
    # 4. Link Budget Calculation
    LightSpeedC = 3e8
    BlueTooth = 2400e6 
    Freq = BlueTooth
    TXAntennaGain = 1  
    RXAntennaGain = 1  
    Dref = 0.5         
    PTx = 0.001        
    PathLossExponent = 3
    Wavelength = LightSpeedC / Freq
    
    PTxdBm = 10 * np.log10(PTx * 1000)
    M = Wavelength / (4 * np.pi * Dref)
    Pr0 = PTxdBm + TXAntennaGain + RXAntennaGain - (20 * np.log10(1/M))
    
    recpower = Pr0 - (10 * PathLossExponent * np.log10(d / Dref)) - mean_power
    
    # 5. Tính toán SNR
    MinimumSNR = 5
    MS = db2pow(MinimumSNR)
    ReceiverSensitivity = -85
    SNR = -1 * ReceiverSensitivity + recpower
    SNR_u = db2pow(SNR)
    
    K = (a_rician**2) / (2 * (b**2))
    
    # 6. Tính hàm Marcum Q
    a_marcum = np.sqrt(2 * K)
    b_marcum = np.sqrt(2 * (K + 1) * MS) / SNR_u
    
    RPnoise_rician = ncx2.sf(b_marcum**2, 2, a_marcum**2)
    
    return RPnoise_rician

def create_rician_lut(filename="rician_LUT.csv", max_distance=200, step=1):
    print("Bắt đầu tạo Look-up Table. Quá trình này có thể mất vài phút...")
    
    distances = np.arange(1, max_distance + 1, step)
    probabilities = []
    
    start_time = time.time()
    for d in distances:
        prob = receptionprob_rice(d)
        probabilities.append(prob)
        
        if d % 10 == 0:
            print(f"Đã xử lý khoảng cách {d}m...")
            
    df = pd.DataFrame({
        'Distance_m': distances,
        'Success_Prob': probabilities
    })
    
    df.to_csv(filename, index=False)
    
    end_time = time.time()
    print(f"Hoàn tất! Đã lưu kết quả vào {filename}.")
    print(f"Thời gian chạy: {end_time - start_time:.2f} giây.")

if __name__ == "__main__":
    create_rician_lut("rician_LUT.csv", max_distance=40 )