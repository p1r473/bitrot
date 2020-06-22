from hashlib import sha256, sha512
# chunk_size = 1048576
chunk_size = 1048576

import time
with open('K:\\1.txt', 'rb') as fd:
    d = fd.read(chunk_size)
    while d:
        d = fd.read(chunk_size)
    fd.close

starttime = time.time()
for i in range(50):
    print(i, sha512(d).hexdigest())
endtime = time.time()
print("Diff: %d", (endtime - starttime))
