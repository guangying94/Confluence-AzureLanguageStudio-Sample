import logging
import azure.functions as func
from wsgiref import headers
from markdownify import markdownify as md
import re
from bs4 import BeautifulSoup as BSHTML
import urllib.parse
import requests
import json
import os
from datetime import datetime, timedelta
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, generate_blob_sas, BlobSasPermissions

### Confluence Configuration
ConfluenceToken = os.environ['CONFLUENCE_TOKEN']
ConfluenceEndpoint = os.environ['CONFLUENCE_ENDPOINT']

### Azure Storage Configuration
BlobStorageAccountName = os.environ['BLOB_ACCOUNT_NAME']
BlobStorageUrl = os.environ['AZURE_STORAGE_URL']
BlobContainerName = os.environ['BLOB_CONTAINER_NAME']
BlobConnectionString = os.environ['STORAGE_CONNECTION_STRING']
BlobAccountKey = os.environ['STORAGE_ACCOUNT_KEY']

### Cognitive Services Configuration
CognitiveServicesKey = os.environ['COGNITIVE_KEY']
CognitiveServicesEndpoint = os.environ['COGNITIVE_ENDPOINT']
LanguageStudioProjectName = os.environ['LANGUAGE_STUDIO_NAME']

credential = DefaultAzureCredential()

def GetPageContent(contentId):
    ## to extend page content
    url = ConfluenceEndpoint + '/rest/api/content/' + contentId + '?expand=body.storage'
    headers = {"Authorization": "Bearer " + ConfluenceToken}
    response = requests.get(url, headers=headers)
    result = response.json()
    pageContent = result['body']['storage']['value']
    return (pageContent)

def ConvertToRealHTML(content):
    output = content.replace('</ac:image>','')
    output = re.sub(r'<ac:image ac:height="[0-9]+">','',output)
    output = output.replace('ri:attachment', 'img')
    output = output.replace('ri:filename','src')
    return output

def HandleImageContent(id, content):
    updatedContent = content
    _parse = BSHTML(content,features='lxml')
    listOfImages = _parse.findAll('img')
    for image in listOfImages:
        _imageURL = GetImageContent(id, image['src'])
        updatedContent = updatedContent.replace(image['src'],_imageURL)
    return updatedContent
        

def GetImageContent(id, filename):
    url = ConfluenceEndpoint + '/download/attachments/%s/%s' % (id,urllib.parse.quote(filename))
    headers = {"Authorization": "Bearer " + ConfluenceToken}
    data = requests.get(url, headers=headers)
    fullURL = GenerateAzureStorageUrlWithSAS(data,filename)
    return fullURL

def GenerateAzureStorageUrlWithSAS(data, fileName):
    ## Either use service principal or connection string
    blob_client = BlobClient(BlobStorageUrl,container_name=BlobContainerName,
    blob_name=fileName, credential=credential)
    #blob_client = BlobClient.from_connection_string(BlobConnectionString,BlobContainerName,fileName)
    blob_client.upload_blob(data,overwrite=True)
    
    one_month = timedelta(days=1)
    blobExpiry = datetime.utcnow() + one_month
    blobSAS = generate_blob_sas(account_name=BlobStorageAccountName,
                                container_name=BlobContainerName,blob_name=fileName,
                                permission=BlobSasPermissions(read=True), account_key=BlobAccountKey, protocol='https',
                               expiry=blobExpiry)
    fullURL = '%s/%s/%s?%s' % (BlobStorageUrl, BlobContainerName, fileName,blobSAS)
    ## To encode the url
    fullURL = fullURL.replace(' ','%20')
    return fullURL

def GenerateMarkdownFromHTML(content):
    return md(content)

def CreateCognitiveServiceRequestBody(question,answer,id):
    body = {}
    body['op'] = 'add'
    _value = {}
    _value['id'] = id
    _value['answer'] = answer
    _value['source'] = 'Editorial'
    _value['questions'] = [question]
    _value['metadata'] = {}
    _dialog = {}
    _dialog['isContextOnly'] = False
    _dialog['prompts'] = []
    _value['dialog'] = _dialog
    body['value'] = _value
    return json.dumps(body)

def PostQnAPairToCognitiveServices(body):
    bodyContent = '[' + body + ']'
    headers = {"Ocp-Apim-Subscription-Key":CognitiveServicesKey,"Content-Type":"application/json"}
    url = '%s/language/query-knowledgebases/projects/%s/qnas?api-version=2021-10-01' % (CognitiveServicesEndpoint, LanguageStudioProjectName)
    _request = requests.patch(url,headers=headers,data=bodyContent)
    print(_request.content)
    return _request.status_code

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        req_body = req.get_json()
    except ValueError:
        pass
    else:
        contentid = req_body.get('id')
        contenttitle = req_body.get('title')

    logging.info(f'Received request for {contentid}, {contenttitle}')

    if contentid and contenttitle:
        _rawHTML = GetPageContent(contentid)
        _realHTML = ConvertToRealHTML(_rawHTML)
        cleanHTML = HandleImageContent(contentid, _realHTML)
        cleanMD = GenerateMarkdownFromHTML(cleanHTML)
        body = CreateCognitiveServiceRequestBody(contenttitle,cleanMD,contentid)
        status = PostQnAPairToCognitiveServices(body)

        return func.HttpResponse(f"{contentid} is sent to Azure with status code {status}.",
        status_code=202)
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a contentid in the query string or in the request body",
             status_code=200
        )
