import pandas as pd
from apdu_logger import SessionLocal,APDULog
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.ensemble import RandomForestClassifier
from joblib import dump

def load_data():
  db=SessionLocal();logs=db.query(APDULog).all();db.close()
  df=pd.DataFrame([{"combo":f"{l.apdu_command}|{l.apdu_response}","y":int(l.success)}for l in logs])
  return df

df=load_data()
vec=CountVectorizer(analyzer="char",ngram_range=(1,2))
X=vec.fit_transform(df["combo"]);y=df["y"]
model=RandomForestClassifier(n_estimators=100).fit(X,y)
dump((vec,model),"apdu_model.joblib")
