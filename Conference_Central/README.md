## Task 1:
For Session implementation, I created session as an entity and child of conference.
The name, highlights, speaker, and typeofsession where StringProperties.
The date was a date property and the startTime a time property.
speaker and typeOfSession were repeated so multiple values could be stored.
I had to create 2 resource containers with the conference key in them and use
them in the endpoints getConferenceSessions and getConferenceSessionsByType.


For Speaker, I defined it as just a string.
When being used for the getSessionBySpeaker endpoint, I created SPEAKER_QUERY_REQUEST
container with just the speaker to be stored in it. I then query Session speakers 
and if they're the same, they're returned.
