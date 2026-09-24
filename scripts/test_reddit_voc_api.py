import requests, json
urls = [
  "https://api.pullpush.io/reddit/search/comment/?q=walking%20pad&size=3",
  "https://api.pullpush.io/comment?q=walking%20pad&size=3",
  "https://arctic-shift.photon-reddit.com/api/posts/search?query=walking%20pad&limit=3&sort=desc"
]
for u in urls:
    try:
        r=requests.get(u,timeout=30,headers={"User-Agent":"walking-pad-voc/1.0"})
        print("URL",u,"STATUS",r.status_code,"LEN",len(r.content))
        print(r.text[:1000].replace("\n"," "))
    except Exception as e:
        print("ERR",u,repr(e))
