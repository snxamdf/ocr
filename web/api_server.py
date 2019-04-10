#-*- coding:utf-8 -*- 
from flask import Flask,jsonify,request,abort,render_template
import base64,cv2,json,sys,numpy as np
import sys,logging,os
sys.path.insert(0,'/Users/piginzoo/workspace/opensource/ctpn')
sys.path.insert(0,'/app.fast/projects/ctpn')
sys.path.insert(0,'/Users/piginzoo/workspace/opensource/crnn')
sys.path.insert(0,'/app.fast/projects/crnn')
import tensorflow as tf
from threading import current_thread
sys.path.append(".")
import ocr_utils

# 定义各类参数
def init_arguments():

    # gunicorn -w 2 -k gevent web.api_server:app -b 0.0.0.0:8080
    tf.app.flags.DEFINE_string('worker-class', 'gevent', '')
    tf.app.flags.DEFINE_integer('workers', 2, '')
    tf.app.flags.DEFINE_string('bind', '0.0.0.0:8080', '')
    tf.app.flags.DEFINE_integer('timeout', 60, '')

    # ctpn的
    tf.app.flags.DEFINE_boolean('debug_mode', True, '')
    tf.app.flags.DEFINE_boolean('evaluate', False, '') # 是否进行评价（你可以光预测，也可以一边预测一边评价）
    tf.app.flags.DEFINE_boolean('split', False, '')    # 是否对小框做出评价，和画到图像上
    tf.app.flags.DEFINE_string('file', '', '')     # 为了支持单独文件，如果为空，就预测test_home中的所有文件
    tf.app.flags.DEFINE_string('gpu', '0', '')
    tf.app.flags.DEFINE_boolean('draw', True, '') # 是否把gt和预测画到图片上保存下来，保存目录也是pred_home
    tf.app.flags.DEFINE_boolean('save', True, '') # 是否保存输出结果（大框、小框信息都要保存），保存到pred_home目录里面去
    tf.app.flags.DEFINE_string('model', '../ctpn/model/', '') # model的存放目录，会自动加载最新的那个模型
    tf.app.flags.DEFINE_string('test_home', 'data/test', '') # 被预测的图片目录
    tf.app.flags.DEFINE_string('pred_home', 'data/pred', '') # 预测后的结果的输出目录

    # crnn的
    tf.app.flags.DEFINE_string('model_dir', "../crnn/model/", 'model dir')
    tf.app.flags.DEFINE_boolean('debug', False, 'debug mode')
    tf.app.flags.DEFINE_string('image_path', '', ' data dir')
    tf.app.flags.DEFINE_string('weights_path', None, 'model path')


# 完事了，才可以import ctpn，否则报错
import main.pred  as ctpn
import tools.pred as crnn

logging.basicConfig(
    format='%(asctime)s : %(levelname)s : %(message)s',
    level=logging.DEBUG,
    handlers=[logging.StreamHandler()])
logger  = logging.getLogger("API Server")

app = Flask(__name__, static_url_path='')
app.jinja_env.globals.update(zip=zip)

logger.debug('子进程:%s,父进程:%s,线程:%r', os.getpid(), os.getppid(),current_thread())


logger.debug("初始化TF各类参数")
init_arguments()

logger.debug("开始初始化CTPN")
sess_ctpn = ctpn.initialize()

logger.debug("开始初始化CRNN")

sess_crnn, charset, decodes, prob, inputdata = crnn.initialize()


#读入的buffer是个纯byte数据
def process(buffer,image_name):
    logger.debug("从web读取数据len:%r",len(buffer))

    if len(buffer)==0: return False,"Image is null"

    #先给他转成ndarray(numpy的)
    data_array = np.frombuffer(buffer,dtype=np.uint8)

    #从ndarray中读取图片，有raw数据变成一个图片rgb数据
    #出来的数据，其实就是有维度了，就是原图的尺寸，如160x70
    image = cv2.imdecode(data_array, cv2.IMREAD_COLOR)
    if image is None:
        logger.error("图像解析失败")#有可能从字节数组解析成图片失败
        return False,None

    logger.debug("从字节数组变成图像的shape:%r",image.shape)

    result = ctpn.pred(sess_ctpn,[image],[image_name])

    for r in result:
        # 从opencv的np array格式，转成原始图像，再转成base64
        r['image'] = ocr_utils.tobase64(r['image'])


    # logger.debug("预测返回结果：%r",result[0])
    small_images = ocr_utils.crop_small_images(image,result[0]['boxes'])
    # small_images = small_images[:2]  # 测试用，为了提高测试速度，只处理2个
    all_txt = []
    for one in small_images:
        logger.debug("small image :%s",one.shape)
        pred_text = crnn.pred(one,sess_crnn,charset,decodes, prob, inputdata)
        all_txt.append(pred_text)

    # 小框们的文本们
    result[0]['text'] = all_txt

    # 小框们的图片的base64
    result[0]['small_images'] = ocr_utils.tobase64(small_images)

    logger.debug("最终的预测结果为：%r",all_txt)
    # logger.debug("最终的预测的子图:%r",result[0]['small_images'])

    return True,result[0]


@app.route("/")
def index():
    # with open("../version") as f:
    #     version = f.read()

    return render_template('index.html',version="version")

#base64编码的图片识别
@app.route('/ocr.64',methods=['POST'])
def ocr_base64():

    base64_data = request.form.get('image','')

    #去掉可能传过来的“data:image/jpeg;base64,”HTML tag头部信息
    index = base64_data.find(",")
    if index!=-1: base64_data = base64_data[index+1:]

    buffer = base64.b64decode(base64_data)
    
    try:
        success,result = process(buffer)
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error("处理图片过程中出现问题：%r",e)
        return jsonify({'success':'false','reason':str(e)}) 
    
    if success: 
        if result is None:
            return jsonify({'success':'false','reason':'image resolve fail'}) 
        else:
            return jsonify({'success':'true','result':result})
    else:
        return jsonify({'success':'false','result':result}) 
    
#图片的识别
@app.route('/ocr',methods=['POST'])
def ocr():

    data = request.files['image']
    image_name = data.filename
    buffer = data.read()
    logger.debug("获得上传图片[%s]，尺寸：%d 字节", image_name,len(buffer))

    success,result = process(buffer,image_name)

    return render_template('result.html', result=result)

#图片的识别
@app.route('/test',methods=['GET'])
def test():
    with open("test/test.png", "rb") as f:
        data = base64.b64encode(f.read())
        data = str(data, 'utf-8')
    aa = ['a2','a1']
    bb = ['b2','b1']
    return render_template('test.html', data=data,aa=aa,bb=bb)


if __name__ == "__main__":
    # 生产代码
    app.run(host='0.0.0.0', port=8080)

    # # 测试代码
    # with open("test/test.png","rb") as f:
    #     image = f.read()
    # process(image,"test.jpg")