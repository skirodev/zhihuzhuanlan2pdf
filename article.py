# -*-coding:utf-8-*-

""" 获取一个知乎专栏中的一篇文章，保持原来的排版，去掉不需要的内容，最终渲染成 html，以便后面转成 pdf
"""

import re
from mako.template import Template
from bs4 import BeautifulSoup
import arrow
import os.path
from session import session


class Article:
    """ 爬取单篇文章"""

    h_replace_table = {'<h1>': '<h2>', '<h2>': '<h3>', '<h3>': '<h4>', '<h4>': '<h5>', '<h5>': '<h6>',
                       '</h1>': '</h2>', '</h2>': '</h3>', '</h3>': '</h4>', '</h4>': '</h5>', '</h5>': '</h6>'}
    img_path = './out/img'  # 图片的保存路径
    pattern = r'\"https://.+?\.(jpg|png)\"'
    article_template = Template(filename='./template/article.html', input_encoding='utf-8')

    def __init__(self):
        self.article = dict()

    @staticmethod
    def utc_to_local(utc):
        """ 将一个UTC格式的时间字符串转为本地时间字符串"""
        utc = arrow.get(utc)
        return utc.format('YYYY-MM-DD HH:mm')

    def get_article_dict(self, url):
        """ 获取 url 指定的一篇知乎专栏文章
        返回一个字典对象，里面包括文章标题、作者、发布时间、文章内容等
        """

        json_obj = session.get(url=url).json()[0]
        self.article['title'] = json_obj['title']
        self.article['title_image_url'] = json_obj['titleImage']
        self.article['author_name'] = json_obj['author']['name']

        # 获取作者头像url
        author_avatar_template = json_obj['author']['avatar']['template']
        avatar_id = json_obj['author']['avatar']['id']
        author_avatar_url = author_avatar_template.replace('{id}', avatar_id).replace('{size}', 'xs')
        self.article['author_avatar_url'] = author_avatar_url
        # 发布时间
        self.article['publishedTime'] = self.utc_to_local(json_obj['publishedTime'])

        # 获取文章内容，这里用另一个api再次请求文章数据
        url2 = 'https://zhuanlan.zhihu.com/api/posts/{0}'.format(json_obj['slug'])
        r = session.get(url=url2).json()
        self.article['content'] = r['content']
        # 获取文章相关主题
        topics = []
        for topic in r['topics']:
            topics.append(topic["name"])
        self.article['topics'] = topics

        # 该文章的评论列表url
        self.article['comments_links'] = 'https://zhuanlan.zhihu.com' + json_obj['links']['comments']
        # 评论数
        self.article['comments_count'] = json_obj['commentsCount']

        return self.article

    @staticmethod
    def _img_download(url):
        """ 下载 url 指定的图片并保存到本地，并返回本地路径"""
        if url is None or len(url) == 0:
            return ''
        # 提取 url 中图片的名称
        name = url[url.rfind('/')+1:]
        # 如果本地已经有该图片就不再下载，节省时间和流量
        path = Article.img_path + '/' + name
        if os.path.isfile(path):
            return './img/' + name
        binary_content = session.get(url=url).content
        with open(file=path, mode='wb') as f:
            f.write(binary_content)

        return './img/' + name

    def images_to_local(self):
        """ 将 self.article 中引用到的所有图片下载到本地，并将 url 指向本地图片，方便后面转成 pdf
        需要处理的图片url包括文章标题中的图片，作者头像，以及正文中的图片"""
        self.article['title_image_url'] = self._img_download(url=self.article['title_image_url'])
        self.article['author_avatar_url'] = self._img_download(url=self.article['author_avatar_url'])

        # 处理文章正文中的图片链接
        def replace(match):
            return self._img_download(match.group(0).strip('\"'))

        self.article['content'] = re.sub(pattern=Article.pattern, repl=replace, string=self.article['content'])
        # TODO:将正则表达式的模式编译成正则表达式对象，可以提高效率

    def handle_lazy_img(self):
        """ 处理正文中的惰性加载图片。因为惰性加载图片是用空白图片占位，后用js代码动态请求图片再替换。
        自己爬取的话，无法执行js代码，所以得自己处理一下"""
        soup = BeautifulSoup(self.article['content'], 'html5lib')
        noscript_blocks = soup.find_all(name='noscript')
        # 将所有noscript块中的图片地址提取出来，赋值给该块下一个兄弟块的img src属性
        for noscript_block in noscript_blocks:
            # 找到img 子节点
            img_node = noscript_block.find('img')
            if img_node:
                # 修改惰性加载的图片src
                for tag in noscript_block.next_siblings:
                    if tag.name == 'img':
                        tag['src'] = img_node['src']
                        break
            # noscript 块不再需要
            noscript_block.decompose()

        self.article['content'] = str(soup)

    def correct_content_titles(self):
        """ 有些文章内容中的会出现h1标签，然而文章名也是h1标签，会导致生成pdf时的标签错误，
        必须将文章内容中出现的h1降级为h2
        """
        def replace(match):
            return Article.h_replace_table.get(match.group(0), match.group(0))

        if re.search(pattern=r'<h1>', string=self.article['content']) is not None:
            # 文章内容中出现 h1 标签，说明需要h系列标签需要降级处理
            self.article['content'] = re.sub(pattern=r'</?h[1-5]>', repl=replace, string=self.article['content'])

    def get_comments(self):
        """ 获取文章的评论列表"""
        json_obj = session.get(self.article['comments_links'] + '?limit=10&offset=0').json()
        self.article['comments'] = []
        for _comment in json_obj:
            comment = dict()
            comment['author_name'] = _comment['author']['name']
            comment['content'] = _comment['content']
            comment['create_time'] = Article.utc_to_local(_comment['createdTime'])
            # 拼接出评论作者的头像url
            _url = _comment['author']['avatar']['template'].replace('{id}', _comment['author']['avatar']['id'])\
                .replace('{size}', 'xs')
            comment['avatar'] = Article._img_download(_url)
            comment['likes_count'] = _comment['likesCount']  # 点赞数
            # 是否属于回复其他人的评论
            comment['reply_to'] = None
            if _comment["inReplyToCommentId"] != 0:
                comment['reply_to'] = _comment["inReplyToUser"]["name"]
            self.article['comments'].append(comment)

    def render_to_html(self):
        """ 将字典对象表示的 self.article 用模板引擎渲染成一个html页面
        返回 HTMl 源码
        """
        return Article.article_template.render(article=self.article).encode('utf-8')

    def get_article_html(self, url):
        """ 获取一篇文章最后的HTML源码"""
        self.get_article_dict(url=url)
        self.images_to_local()
        self.handle_lazy_img()
        self.correct_content_titles()
        self.get_comments()
        return self.render_to_html()


if __name__ == '__main__':

    a = Article()

    with open('./out/out3.html', 'wb') as f:
        f.write(a.get_article_html(url='https://zhuanlan.zhihu.com/api/columns/auxten/posts?limit=1&offset=1'))
