#import csv
#import gspread
#from google_auth_oauthlib.flow import InstalledAppFlow
#scope = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]

#flow = InstalledAppFlow.from_client_secrets_file("Credentials2.json", scopes=scope)
#creds= flow.run_local_server(port=0)
#client = gspread.authorize(creds)
#print([s.title for s in client.openall()])

#sheet = client.open("LINK TO PYTHON2").sheet1

#with open('purchases.csv', mode='r') as file:
#	reader = csv.DictReader(file)
#	for row in reader:
#		sheet.append_row(list(row.values()))
