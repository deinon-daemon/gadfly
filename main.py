import io
import functions_framework

from PIL import Image
from gadfly import gadfly_io
from google.cloud import storage 

client = storage.Client()
bucket = client.bucket('eco_one_images')

def upload_pils(images, names):

  ##print(images)
  ##print(names)

  if len(images) != len(names):
    raise ValueError("Images and names lists must be parallel.")

  pub_urls = []
  for (img, name) in zip(images, names): 

    blob = bucket.blob(name)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    blob.upload_from_file(img_bytes)

    #print(blob.public_url)
    pub_urls.append(blob.public_url)

  return names, pub_urls  

@functions_framework.http
def fly(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    request_json = request.get_json(silent=True)
    ##request_args = request.args

    if request_json and 'url' in request_json:
        url = request_json['url']
        if 'name' in request_json:
          name = request_json['name']
        else:
          name = ''
        if 'entity' in request_json:
          entity = request_json['entity']
        else:
          entity = 'logo'

        if 'prefix' in request_json:
          prefix = request_json['prefix']
        else:
          prefix = 'the logo of'

        Gadfly_io = gadfly_io()

        image_names, images = Gadfly_io.fly(url, name, entity)
        img_names, pub_urls = upload_pils(images, image_names)  

        table_results = []
        for img_name, pub_url in zip(img_names, pub_urls):
          labels_and_scores = Gadfly_io.call_clippy(pub_url, name, prefix)
          #print(str(labels_and_scores))
          labels_and_scores['img_name'] = img_name
          table_results.append(labels_and_scores)

        #print(str(table_results))
        backups = []
        for i, result in enumerate(table_results):
          top_score = result.get('labels_and_scores')[0]
          #print(str(top_score))
          second_score = result.get('labels_and_scores')[1]
          if (top_score.get('text') == f'{prefix} {name}' and second_score.get('text') == 'a company logo') or (top_score.get('text') == f'{prefix} {name}' and top_score.get('score') > .87):
            winner_winner = table_results.pop(i)
            if len(table_results) < 1:
              return winner_winner['url']
            else:
              for rem in table_results:
                blob = bucket.blob(rem.get('img_name'))
                blob.delete()
              return winner_winner.get('url')

          elif top_score.get('text') == f'{prefix} {name}':
            backups.append(result.get('url'))

        return backups[0]    


          
    else:
      return 'Hello {}!'.format(str(request_json) or 'World')
