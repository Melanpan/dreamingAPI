import cv2
import numpy as np

class skinDetect():
    """ Based on https://github.com/CHEREF-Mehdi/SkinDetection/blob/master/SkinDetection.py """
    def __init__(self, image):
        self.img = cv2.imread(image)
    
    def detect(self):
        height, width, channels = self.img.shape

        #converting from gbr to hsv color space
        img_HSV = cv2.cvtColor(self.img, cv2.COLOR_BGR2HSV)
        #skin color range for hsv color space 
        HSV_mask = cv2.inRange(img_HSV, (0, 15, 0), (17,170,255)) 
        HSV_mask = cv2.morphologyEx(HSV_mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))

        #converting from gbr to YCbCr color space
        img_YCrCb = cv2.cvtColor(self.img, cv2.COLOR_BGR2YCrCb)
        #skin color range for hsv color space 
        YCrCb_mask = cv2.inRange(img_YCrCb, (0, 135, 85), (255,180,135)) 
        YCrCb_mask = cv2.morphologyEx(YCrCb_mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))

        #merge skin detection (YCbCr and hsv)
        global_mask= cv2.bitwise_and(YCrCb_mask,HSV_mask)
        global_mask = cv2.medianBlur(global_mask,3)
        global_mask = cv2.morphologyEx(global_mask, cv2.MORPH_OPEN, np.ones((4,4), np.uint8))
        
        return np.sum(global_mask == 255)/(height * width)*100