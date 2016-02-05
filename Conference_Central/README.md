## Task 1:
For Session implementation, I created session as a child of conference. 
I had to create 2 resource containers with the conference key in them and use
them in the endpoints getConferenceSessions and getConferenceSessionsByType.


For Speaker, I created SPEAKER_QUERY_REQUEST container with just the speaker
to be stored in it. I then query Session speakers and if they're the same,
I pass them onto SessionForms to be displayed.
