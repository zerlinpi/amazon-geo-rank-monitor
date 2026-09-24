import requests, json
UA={"User-Agent":"walking-pad-voc/1.0"}
tests=[
("exact","https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=WalkingPads&limit=3&sort=asc&after=2026-01-01&before=2027-01-01&fields=id,title,selftext,created_utc,num_comments,subreddit,permalink"),
("nofields","https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=WalkingPads&limit=3&sort=asc&after=2026-01-01&before=2027-01-01"),
("epoch","https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=WalkingPads&limit=3&sort=asc&after=1767225600&before=1798761600")
]
for name,u in tests:
    try:
        r=requests.get(u,timeout=30,headers=UA)
        print("TEST",name,"STATUS",r.status_code,"LEN",len(r.content))
        print(r.text[:2000].replace("\n"," "))
    except Exception as e:
        print("ERR",name,repr(e))
