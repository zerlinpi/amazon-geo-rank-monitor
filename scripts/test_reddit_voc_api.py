import requests, concurrent.futures, json
BASE="https://arctic-shift.photon-reddit.com/api/comments/search/aggregate"
UA={"User-Agent":"walking-pad-voc-count/1.0"}
pure=["WalkingPads","walkingdesks"]
subs=["treadmills","StandingDesks","WFH","walking","workingmoms","PetiteFitness","loseit","CICO","homeoffice","productivity","fitness"]
terms=["walking pad","walkingpad","under desk treadmill","desk treadmill","walking treadmill","treadmill desk","walking desk","urevo","deerrun","sperax","kingsmith","egofit","goyouth","merach","toputure","wellfit"]
jobs=[(s,None) for s in pure]+[(s,t) for s in subs for t in terms]
def one(x):
 s,t=x
 p={"aggregate":"created_utc","frequency":"year","subreddit":s}
 if t:p["body"]=t
 try:
  r=requests.get(BASE,params=p,headers=UA,timeout=40)
  if r.status_code!=200:return (s,t,-1,r.status_code)
  j=r.json(); data=j.get("data") or []
  total=0
  for z in data:
   if isinstance(z,dict):
    for k in ("count","doc_count","value"):
     if isinstance(z.get(k),(int,float)): total+=int(z[k]); break
  return (s,t,total,200)
 except Exception:return (s,t,-2,0)
out=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
 for r in concurrent.futures.as_completed([ex.submit(one,j) for j in jobs]): out.append(r)
for r in sorted(out,key=lambda x:x[2],reverse=True):
 print(json.dumps({"sub":r[0],"term":r[1],"count":r[2],"status":r[3]}))
