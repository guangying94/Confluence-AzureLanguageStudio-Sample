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
from dotenv import load_dotenv

load_dotenv()

## Define environment variable
### Confluence Configuration
token = os.environ['CONFLUENCE_TOKEN']
ConfluenceEndpoint = os.environ['CONFLUENCE_ENDPOINT']

### Custom configuration
ConfluencePageListEndpoint = '/rest/api/content/search?cql=(space=GB%20and%20type=page)'
NonHowToArticleList = ['gutee knowledge base','How-to articles']

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

def main():
    print('Get the list of pages in knowledge base')
    rawPageList = GetKBPageList()
    ######
    print('Extract list of page ID')
    ######
    toBeExtractPageList = []
    for result in rawPageList['results']:
        _tempID = result['id']
        if not (result['title'] in NonHowToArticleList):
            pageDetail = {}
            pageDetail['id'] = _tempID
            pageDetail['url'] = result['_links']['self']
            pageDetail['title'] = result['title']
            toBeExtractPageList.append(pageDetail)
    #####
    print('Identified %i page(s) to be processed' % len(toBeExtractPageList))
    #####
    KBList = [{} for i in range(len(toBeExtractPageList))]
    pageCount = 0
    for page in toBeExtractPageList:
        print('Processing page id %s' % page['id'])
        _rawHTML = GetPageContent(page['url'])
        _realHTML = ConvertToRealHTML(_rawHTML)
        cleanHTML = HandleImageContent(page['id'], _realHTML)
        cleanMD = GenerateMarkdownFromHTML(cleanHTML)
        _pair = CreateCognitiveServiceRequestBody(page['title'],cleanMD,page['id'])
        KBList[pageCount] = _pair
        pageCount = pageCount + 1
    #####
    PostQnAPairToCognitiveServices(KBList)
    print('Completed!')

def GetKBPageList():
    url = ConfluenceEndpoint + ConfluencePageListEndpoint
    headers = {"Authorization": "Bearer " + token}
    response = requests.get(url, headers=headers)
    return (response.json())

def GetPageContent(pageUrl):
    ## to extend page content
    url = pageUrl + '?expand=body.storage'
    headers = {"Authorization": "Bearer " + token}
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
    headers = {"Authorization": "Bearer " + token}
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

def PostQnAPairToCognitiveServices(body):
    print(len(body))
    bodyContent = '['
    for page in body:
        bodyContent = bodyContent + page + ','
    bodyContent = bodyContent[:-1]
    bodyContent = bodyContent + ']'
    print(bodyContent)
    headers = {"Ocp-Apim-Subscription-Key":CognitiveServicesKey,"Content-Type":"application/json"}
    url = '%s/language/query-knowledgebases/projects/%s/qnas?api-version=2021-10-01' % (CognitiveServicesEndpoint, LanguageStudioProjectName)
    _request = requests.patch(url,headers=headers,data=bodyContent)
    print(_request.content)

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

if __name__ == "__main__":
    main()
