from genesis.com import *
from genesis.utils import shell, shell_cs, download

import os
import shutil


class InstallError(Exception):
	def __init__(self, cause):
		self.cause = cause

	def __str__(self):
		return 'Installation failed: %s' % self.cause

class PartialError(Exception):
	def __init__(self, cause):
		self.cause = cause

	def __str__(self):
		return 'Installation successful, but %s' % self.cause

class ReloadError(Exception):
	def __init__(self, cause):
		self.cause = cause

	def __str__(self):
		return 'Installation successful, but %s restart failed. Check your configs' % self.cause


class WABackend:
	def add(self, name, webapp, vars, enable=True):
		if not webapp.dpath.endswith('.tar.gz'):
			raise InstallError('Only .tar.gz packages supported for now')

		# Make sure the target directory exists, but is empty
		# Testing for sites with the same name should have happened by now
		target_path = os.path.join('/srv/http/webapps', name)
		if os.path.isdir(target_path):
			shutil.rmtree(target_path)
		os.makedirs(target_path)

		# Download and extract the source package
		try:
			download(webapp.dpath, file='/tmp/'+name+'.tar.gz')
		except Exception, e:
			raise InstallError('Couldn\'t download - %s' % str(e))
		status = shell_cs('tar xzf /tmp/'+name+'.tar.gz -C '
			+target_path+' --strip 1')
		if status[0] >= 1:
			raise InstallError(status[1])

		# Setup the webapp and create an nginx serverblock
		try:
			webapp.install(name, target_path, vars)
		except Exception, e:
			raise InstallError('Webapp config - '+str(e))

		try:
			self.nginx_add(
				name=name, 
				stype=webapp.name, 
				path=target_path, 
				addr=vars.getvalue('addr', 'localhost'), 
				port=vars.getvalue('port', '80'), 
				add=webapp.addtoblock, 
				php=(True if webapp.php is True else False)
				)
		except Exception, e:
			raise PartialError('nginx serverblock couldn\'t be written - '+str(e))

		if enable is True:
			try:
				self.nginx_enable(name)
			except:
				raise ReloadError('nginx')
		if enable is True and webapp.php is True:
			try:
				self.php_enable()
				self.php_reload()
			except:
				raise ReloadError('PHP-FPM')

	def remove(self, name, webapp):
		path = os.path.join('/srv/http/webapps', name)
		if webapp == '':
			f = open('/etc/nginx/sites-available/'+name, 'r')
			for line in f.readlines():
				if 'root' in line:
					path = line.split()[1].rstrip(';')
					break
		else:
			webapp.remove(name, path)
		shutil.rmtree(path)
		self.nginx_remove(name)

	def nginx_add(self, name, stype, path, addr, port, add='', php=False):
		if path == '':
			path = os.path.join('/srv/http/webapps/', name)
		phploc = (
			'	location ~ \.php$ {\n'
			'		fastcgi_pass unix:/run/php-fpm/php-fpm.sock;\n'
			'		fastcgi_index index.php;\n'
			'		include fastcgi.conf;\n'
			'	}\n'
			)
		f = open('/etc/nginx/sites-available/'+name, 'w')
		f.write(
			'# GENESIS '+stype+' http://'+addr+'\n'
			'server {\n'
			'   listen '+port+';\n'
			'   server_name '+addr+';\n'
			'   root '+path+';\n'
			'   index index.'+('php' if php else 'html')+';\n'
			+(phploc if php else '')
			+(add if add is not '' else '')+
			'}\n'
			)
		f.close()

	def nginx_remove(self, sitename, reload=True):
		try:
			self.nginx_disable(sitename, reload)
		except:
			pass
		os.unlink(os.path.join('/etc/nginx/sites-available', sitename))

	def nginx_enable(self, sitename, reload=True):
		origin = os.path.join('/etc/nginx/sites-available', sitename)
		target = os.path.join('/etc/nginx/sites-enabled', sitename)
		if not os.path.exists(target):
			os.symlink(origin, target)
		if reload == True:
			self.nginx_reload()

	def nginx_disable(self, sitename, reload=True):
		os.unlink(os.path.join('/etc/nginx/sites-enabled', sitename))
		if reload == True:
			self.nginx_reload()

	def nginx_reload(self):
		status = shell_cs('systemctl restart nginx')
		if status[0] >= 1:
			raise

	def php_enable(self):
		shell('sed -i "s/.*include \/etc\/nginx\/php.conf.*/\tinclude \/etc\/nginx\/php.conf;/" /etc/nginx/nginx.conf')

	def php_disable(self):
		shell('sed -i "s/.*include \/etc\/nginx\/php.conf.*/\t#include \/etc\/nginx\/php.conf;/" /etc/nginx/nginx.conf')

	def php_reload(self):
		status = shell_cs('systemctl restart php-fpm')
		if status[0] >= 1:
			raise