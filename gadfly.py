import os
import io
import re
import json
import pdf2image
import requests
import numpy as np
import cloudscraper
from os import path
from PIL import Image
from bs4 import BeautifulSoup
from Levenshtein import distance
from svglib.svglib import svg2rlg
from sklearn.cluster import KMeans
from reportlab.graphics import renderPDF
from urllib.parse import urljoin, urlsplit
from skimage.exposure import is_low_contrast
# Root path on CF will be /workspace, while on local Windows: C:\
root = path.dirname(path.abspath(__file__))


class gadfly_io:

  def __init__(self):
    self.scraper = cloudscraper.CloudScraper()

  def scrape_images(self, link, name='', entity='logo'):
    '''
    Get images via scrapfly client, check all the best tags and selectors,
    Use Levenshtein NLP to ensure images w/ alt text that resembles the value in the param "name" are
    Returned more often :)

    Avg. execution ==> 7s/url
    '''
    url = f"https://api.scrapfly.io/scrape?key={key}&url={link}&tags=lazy_shoggoth_images%2Cimage_pipeline&proxy_pool=public_residential_pool&debug=false&country=us&asp=true&render_js=true"

    raw_response = requests.request("GET", url)

    response = json.loads(raw_response.text)

    if response['result']['status_code'] > 299:
      return None, response['status_code']

    html = response['result']['content']
    soup = BeautifulSoup(html, 'html.parser')

    header_imgs = [urljoin(link, img.get('src')) for img in soup.select('header img')]
    footer_imgs = [urljoin(link, img.get('src')) for img in soup.select('footer img')]
    head_imgs = [urljoin(link, img.get('src')) for img in soup.select('head img')]
    link_imgs = [urljoin(link, l.get('href')) for l in soup.select('link[rel="image_src"]')] + [urljoin(link, l.get('href')) for l in soup.select('link[rel="icon"]')]
    meta_imgs = [urljoin(link, meta.get('content')) for meta in soup.select('meta[property="og:image"]')]

    agg_imgs = header_imgs + footer_imgs + head_imgs + link_imgs + meta_imgs

    alt_imgs = soup.select('img')
    name = name.lower()
    for alt in alt_imgs:
      alt_obj = alt.get('alt') or 'none'
      if not alt_obj or alt_obj == 'none' or type(alt_obj) != str:
        continue
        
      alt_text = alt_obj.lower()

      if name in alt_text and entity in alt_text:
        agg_imgs.append(urljoin(link, alt.get('src')))

      if not agg_imgs or len(agg_imgs) < 1:

        if alt_text != '' and alt_text != ' ' and distance(f"{name} {entity}".lower(), alt_text) < 5:
          agg_imgs.append(urljoin(link, alt.get('src')))

        if not agg_imgs or len(agg_imgs) < 2:

          if name in alt_text:
            agg_imgs.append(urljoin(link, alt.get('src')))


    agg_imgs = set(agg_imgs)

    #print('Agg Image Count: ', len(agg_imgs))
    #print('Agg Images: ', agg_imgs)

    return agg_imgs


  ############ ^^^ IMAGE COLLECTION ^^^ ##################

  ############ <<< IMAGE POST PROCESSING >>> ################

  def has_transparency(self, img):

    # Convert to RGBA if needed
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # Check for alpha channel
    for pixel in img.getdata():
        if pixel[3] < 255:
            return True

    return False

  def get_bg_color(self, img):

    # Flatten image to 1D array
    pix = np.asarray(img).reshape(-1,1)

    # Cluster pixels into 2 groups (foreground and background)
    kmeans = KMeans(n_init=10, n_clusters=2).fit(pix)

    # Get cluster center for larger cluster
    bg_color = kmeans.cluster_centers_[np.argmax(kmeans.cluster_centers_[:,0])]

    # Convert to int
    bg_color = int(bg_color[0])

    # Create 3-tuple
    return (bg_color, bg_color, bg_color)


  def make_square(self, img, filler_color=(255, 255, 255), transparent=False):

    width, height = img.size

    # Make a new square image with the filler color (background color)
    new_size = max(width, height)

    #print(filler_color)
    # Make new RGBA image w/ correct sizing
    new_img = Image.new('RGBA', (new_size, new_size), filler_color)

    if transparent:
      # Paste image on top to fill
      offset = (int((new_size - width) / 2), int((new_size - height) / 2))
      new_img.paste(img.convert('RGBA'), offset, img.convert('RGBA'))
      return new_img

    else:
      # Paste the original image in the center
      offset = (int((new_size - width) / 2), int((new_size - height) / 2))
      new_img.paste(img.convert('RGB'), offset)
      return new_img

  def fix_bg(self, img, bg_color=(255, 255, 255)):

    # Generate complement
    fallback_color = tuple(255 - c for c in bg_color)

    # Create and display fallback image
    new_background = Image.new('RGB', img.size, color=fallback_color)
    new_background.paste(img.convert('RGBA'), (0,0), img.convert('RGBA'))
    return fallback_color, new_background

  def url_filter(self, urls):
    filtered_urls = []

    for url in urls:
      if re.search(r'\.(png|jpeg|svg|webp)$', url):
        ## re.search(r'\.(png|jpeg|svg|webp|ico)$', url) ?? TODO: ask denise is favicons are kühl or nah
        filtered_urls.append(url)

    return filtered_urls


  def post_process(self, image, threshold=0.3, lower_percentile=1, upper_percentile=99):

    # Get Background Color of incoming image
    bg_color = self.get_bg_color(image)

    # Test transparency
    is_transparent = self.has_transparency(image)
    if is_transparent:
      #print("Transparent!")

      # Run fix background
      fallback_color, contrast_img = self.fix_bg(image, bg_color)
      return self.make_square(contrast_img, fallback_color, True)

    # (Else) Convert to array
    image_arr = np.asarray(image)

    # Check contrast ratio
    contrast = is_low_contrast(
        image_arr,
        fraction_threshold=threshold,
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile
    )

    # If low contrast...
    if contrast:
      #print("Low contrast. Setting fallback color.")

      # Fix background for contrast issues
      fallback_color, contrast_img = self.fix_bg(image, bg_color)
      return self.make_square(contrast_img, self.get_bg_color(contrast_img))
    else:
      return self.make_square(image, bg_color)

  def get_top_k(self, image_urls):

    MIN_SIZE = 30 # min height/width in pixels for a valid logo

    valid_urls = self.url_filter(image_urls)
    if not valid_urls:
      return None

    filtered_urls = []
    images = []

    for url in valid_urls:
      try:

        if url.endswith('.svg'):
          pdf_bytes = io.BytesIO()
          renderPDF.drawToFile(svg2rlg(io.BytesIO(self.scraper.get(url).content)), pdf_bytes) ## convert svg => pdf => png (TRUST ME, necessary)
          doc = doc = pdf2image.convert_from_bytes(pdf_bytes.getvalue(), thread_count = 5, strict=True, fmt='png', poppler_path=path.join(root, '/poppler-0.68.0/bin')) # open document 

          ### OR ###
          ## fitz.open(stream=pdf_bytes.getvalue(), filetype='pdf')  
          # render page to a pixmap RGB image
          ## pixmap=doc[0].get_pixmap(alpha=False) 
          # stream back as bytes
          ## image = io.BytesIO(pixmap.tobytes()))
          ### END OR ###

          img = doc[0]
          title= '-'.join(urlsplit(url)[1:3]).replace('/','').replace('.','-')


          ## outfile = f"{title}.png"

          # Save PNG bytes to local temp file

          ## with open(outfile, "wb") as f:
              #f.write(png_bytes)

          # save local file path as url/"uri" for later
          ## localpath = os.path.abspath(temp_file)


          #print(title)
          filtered_urls.append(title)


        else:
          img = Image.open(io.BytesIO(self.scraper.get(url).content))
          w, h = img.size

          if w >= MIN_SIZE and h >= MIN_SIZE:
            filtered_urls.append(url)
            image = self.post_process(img)
            images.append(image)
          else:
            print('image too small: ', url)


      except Exception as e:
        # Ignore any errors in opening the image [just print for debugging]
        print('ERROR IN IMAGE PROCESSING: ', e)
        pass

    return filtered_urls, images

############ ^^^ END OF IMAGE POST PROCESSING ^^^ ################


############ <<< CV POST PROCESSING && RUNTIME ORCHESTRATOR >>> ################

  def call_clippy(self, uri, name='a tech company or university', prefix='the logo of'):
    endpoint = jina_api_endpoint
    data = json.dumps({"data": [
      {"uri": uri,
      "matches": [
          {"text": "a company logo"},
          {"text": "a photo of a person"},
          {"text": "a photo of an animal"},
          {"text": "the facebook logo"},
          {"text": "the google logo"},
          {"text": "the instagram logo"},
          {"text": "a social media logo"},
          {"text": "abstract art"},
          {"text": "a photo of nothing"},
          {"text": f"{prefix} {name}"},
          ]}], "execEndpoint":"/rank"})
    resp = requests.post(
        endpoint,
        data=data,
        headers= {
            "Content-Type": "application/json",
            "Authorization": jina_key
            }
        )

    matches = [item for item in json.loads(resp.content)['data'][0]['matches']]
    labels_scores = []

    for m in matches[:2]:
      text = m['text']
      score = m['scores']['clip_score']['value']
      cos_score = m['scores']['clip_score_cosine']['value']
      labels_scores.append({"text": text, "score": score, "cos_score": cos_score})
      #print(str({"text": text, "score": score, "cos_score": cos_score}))

    return {"url": uri, "labels_and_scores": labels_scores}


  def fly(self, source_url, name='', entity='logo'):
    image_urls = list(self.scrape_images(source_url, name, entity))
    filtered_urls, images = self.get_top_k(image_urls)

    return filtered_urls, images




