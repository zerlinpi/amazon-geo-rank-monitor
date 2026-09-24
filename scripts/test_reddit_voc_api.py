import requests, json
UA={"User-Agent":"walking-pad-voc/1.0"}
tests=[
("posts","https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=WalkingPads&limit=3&sort=desc"),
("postsq","https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=treadmills&query=walking%20pad&limit=3&sort=desc"),
("tree","https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=t3_1vv6j5k&limit=100")
]
for name,u in tests:
    try:
        r=requests.get(u,timeout=30,headers=UA)
        print("TEST",name,"STATUS",r.status_code,"LEN",len(r.content))
        print(r.text[:3000].replace("\n"," "))
    except Exception as e:
        print("ERR",name,repr(e))
