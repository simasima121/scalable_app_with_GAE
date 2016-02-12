#Project: Scalable App with GAE
App Engine application for the Udacity training course.
It's a conference organisation app.

##Required Libraries and Dependencies
### Products
- [App Engine][1]

### Language
- [Python][2]

### APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

##How to Run Project
1. Open GoogleAppEngineLauncher
2. Add Existing Application to the GoogleAppEngineLauncher using **file -> add existing application**
3. Choose port addresses 
4. Press run button and navigate to [localhost:<Port>]
5. To view backend explorer, type [localhost:<Port>/_ah/api/explorer]
5. When ready, press Deploy button in GoogleAppEngineLauncher
6. Navigate to <application id>.appspot.com to view deployed app.

##Miscellaneous
Must have Google account to login and must create own app on their developer pages



[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool