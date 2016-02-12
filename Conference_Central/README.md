## Task 1:
For Session implementation, I created session as an entity and child of conference (therefore when being created, its parent key is given as a conference key.)
* The name, highlights, speaker, and typeofsession where StringProperties.
* The date was a date property and the startTime a time property.
* typeOfSession were repeated so multiple values could be stored.
* I had to create 2 resource containers with the conference key in them and use them in the endpoints getConferenceSessions and getConferenceSessionsByType.

I defined speaker just a string as opposed to its own entity.
When being used for the getSessionBySpeaker endpoint, I created the SPEAKER_QUERY_REQUEST container with just the speaker to be stored in it. I then query Session speakers and if they're the same, they're returned.

## Task 3:
The 2 endpoints created were getSessionsByDate and getSessionsByTime.
The purpose of the queries is that given a date or start time, the user can 
see all the sessions that start at those times and dates.
I also created the getSessions endpoint which returns all sessions - it's a 
super simple query!

The problem with the query is you cannot use 2 inequalities on different properties. 
To solve this:

1. filter `startTime: sessions = Session.filter(Session.startTime < 19:00)`
2. create a dictionary with all the Sessions. Use a for loop to go through the dictionary and if the `typeOfSession`is not workshop`, append these sessions to another array and return these.
```for type in dict:
	if type not "workshop":
		filtered_sessions = sessions.filter(Session.typeOfSession == type)
		wanted_sessions.append(filtered_sessions)
return wanted_sessions```


