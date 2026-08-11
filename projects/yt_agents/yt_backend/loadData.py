import pandas as pd
from yt_backend.db import engine

def to_seconds(t):
    h, m, s = map(int, t.split(":"))
    return h*3600 + m*60 + s

df = pd.read_csv("agents/data/Call-Center-Data.csv")

df["Answer Speed (AVG)"] = df["Answer Speed (AVG)"].apply(to_seconds)
df["Talk Duration (AVG)"] = df["Talk Duration (AVG)"].apply(to_seconds)
df["Waiting Time (AVG)"] = df["Waiting Time (AVG)"].apply(to_seconds)

df["Answer Rate"] = df["Answer Rate"].str.replace("%", "").astype(float)
df["Service Level (20 Seconds)"] = df["Service Level (20 Seconds)"].str.replace("%", "").astype(float)

df = df.rename(columns={
    "Index": "id",
    "Incoming Calls": "incoming_calls",
    "Answered Calls": "answered_calls",
    "Abandoned Calls": "abandoned_calls",
    "Answer Rate": "answer_rate",
    "Service Level (20 Seconds)": "service_level_20s",
    "Answer Speed (AVG)": "answer_speed_avg",
    "Talk Duration (AVG)": "talk_duration_avg",
    "Waiting Time (AVG)": "waiting_time_avg",
})

df.to_sql("call_center_data", engine, if_exists="append", index=False)
