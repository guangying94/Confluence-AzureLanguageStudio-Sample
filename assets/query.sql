WITH updates AS(
SELECT CONTENTID, TITLE, VERSION, CREATIONDATE, LASTMODDATE
 FROM [dbo].[CONTENT]
 WHERE LASTMODDATE > DATEADD(hour, -12, SYSDATETIME()) AND CONTENT_STATUS = 'current' AND CONTENTTYPE = 'PAGE'
 ),
latest_content AS(
SELECT TITLE, MAX(VERSION) as LATEST
FROM [dbo].[CONTENT]
GROUP BY TITLE, CONTENT_STATUS, CONTENTTYPE
HAVING CONTENT_STATUS = 'current' AND CONTENTTYPE = 'PAGE'
)
SELECT l.TITLE, l.LATEST, u.CONTENTID, u.CREATIONDATE, u.LASTMODDATE
FROM latest_content l
INNER JOIN updates u
ON l.TITLE = u.TITLE AND l.latest = u.VERSION